# -*- coding: utf-8 -*-
"""Índice de Direcionamento de Certame — score contextual agregado 0-100 (Task 4.3 da F4).

Método (docs/BENCHMARKS-EXTERNOS.md §3.2 — CRI/Fazekas + OCP/Cardinal + ARACHNE):
  1. Flags agrupados em 6 FAMÍLIAS (transparencia, competicao, conluio, fraude_cadastral,
     preco, execucao); **MÁXIMO por família** antes de ponderar — nunca soma: evita dupla
     contagem de flags correlacionados (single-bidding + poucos licitantes + cláusula
     restritiva são o MESMO fenômeno visto por 3 janelas).
  2. Score 0-100 = média ponderada (`_PESOS_FAMILIA`) das famílias APURÁVEIS, renormalizada
     pelos pesos apuráveis — família INDISPONÍVEL não zera nem pontua (INDISPONÍVEL ≠ 0);
     ela só reduz `confianca` = famílias apuráveis / 6.
  3. **Materialidade NUNCA entra no risco** (padrão TCU): `prioridade = score ×
     log1p(valor_total_certame)` — certame caro sobe na fila, não no risco.
  4. Matriz S×V no contrato de `reporting/relatorio_direcionamento._matriz_risco`
     (severidade × verossimilhança 1-5, régua 1-4/5-9/10-15/16-25) — reimplementada mínima
     aqui em dict (o original devolve HTML acoplado à ficha).

DECISÕES DE JOIN (verificadas contra data/compliance.db em 2026-07-19):
  • `clausula_veredito.numero_controle_pncp` CASA com `pncp_resultado.certame` (mesma chave
    de COMPRA "-1-"; 226 casamentos reais) → restritividade entra na família COMPETICAO.
  • `contrato_aditivo.numero_controle_pncp` é chave de CONTRATO ("-2-") ≠ chave de compra
    ("-1-") e NÃO há tabela-ponte compra→contrato → 0 casamentos. A família EXECUCAO fica
    INDISPONÍVEL honesta enquanto não existir o vínculo; a query fica implementada para o
    dia em que a ponte existir.
  • `preco_referencia_cache` é chaveada por CATMAT, que `pncp_resultado` não tem → sobrepreço
    usa a mediana de `pncp_resultado.valor_unitario` do mesmo item normalizado (`_norm_item`),
    entre OUTROS certames (guarda anti-artefato de 10% da mediana, como `comparador_precos`).
  • Licitante único: o registro PNCP típico só traz o VENCEDOR (ordem_classificacao=1) —
    "1 fornecedor distinto" NÃO prova licitante único. O flag só é apurável quando há lances
    em `proposta_item` (a ata lista TODOS os proponentes) ou quando o próprio PNCP registrou
    ordem>1 (prova de que classificações além do vencedor foram gravadas).

REGRAS DE HONESTIDADE: indício ≠ acusação (presunção de legitimidade); tabela ausente =
fonte não coletada = INDISPONÍVEL; score = indício interno de priorização, nunca conclusão.
⚠️ Pesos = ponto de partida dos benchmarks; ARACHNE ensina que score sem calibração local
vira ruído — recalibrar contra desfechos RJ (vencedor depois sancionado, sobrepreço real).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3

from pathlib import Path

from compliance_agent.cruzamentos_intel import _mediana, _norm_item
from compliance_agent.editais.db import DDL_CERTAME_INDICE, conectar
from compliance_agent.editais.screens_conluio import screens
from compliance_agent.emendas.db import _DB_PADRAO


def _conectar_ro(db_path=None) -> sqlite3.Connection:
    """Leitura sempre em mode=ro (regra da casa): o cálculo nunca escreve nem segura lock."""
    p = Path(db_path) if db_path else _DB_PADRAO
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con

FAMILIAS = ("transparencia", "competicao", "conluio", "fraude_cadastral", "preco", "execucao")

# ── Pesos por família (Σ=1.0). Fundamento: Banca d'Italia (Decarolis-Giorgiantonio 2022) —
# flags de DISCRICIONARIEDADE/competição predizem corrupção; urgência/publicidade foram não
# ou negativamente correlacionados → competicao+conluio carregam metade do peso e
# transparencia fica no piso. CRI/Fazekas: componente só pesa se prediz single-bidding e
# correlaciona com sobrepreço → preco/fraude_cadastral intermediários; execucao (aditivos)
# é sinal tardio (já contratado) → peso menor.
_PESOS_FAMILIA = {
    "transparencia": 0.10,
    "competicao": 0.25,
    "conluio": 0.25,
    "fraude_cadastral": 0.15,
    "preco": 0.15,
    "execucao": 0.10,
}

# Faixas do score 0-100 (contrato da tabela certame_indice)
FAIXA_BAIXO_MAX = 25.0
FAIXA_MEDIO_MAX = 50.0
FAIXA_ALTO_MAX = 75.0

LIMIAR_DRIVER = 0.5            # família ≥ 0.5 vira driver (flag máximo + evidência textual)

# Modalidades PNCP (Manual de Integração PNCP / Lei 14.133): 8=dispensa (art. 75),
# 9=inexigibilidade (art. 74). Inexigibilidade = juízo discricionário puro → intensidade
# máxima (Banca d'Italia: discricionariedade é o preditor); dispensa tem hipóteses objetivas.
MODALIDADE_DISPENSA = 8
MODALIDADE_INEXIGIBILIDADE = 9
VALOR_FLAG_INEXIGIBILIDADE = 1.0
VALOR_FLAG_DISPENSA = 0.7
VALOR_FLAG_SEM_DATA_PUB = 0.4  # registro incompleto no PNCP = opacidade documental (fraca)

# Competição: gradação por nº de proponentes (CRI usa single-bidding como âncora)
VALOR_LICITANTE_UNICO = 1.0
VALOR_DOIS_LICITANTES = 0.5
VALOR_TRES_LICITANTES = 0.25
MIN_LICITANTES_SAUDAVEL = 4    # ≥4 proponentes → flag de competição = 0

ESCALA_FANTASMA = 100.0        # fantasma_score.score é 0-100 (observado 0-68 na base)
SOBREPRECO_FATOR = 2.0         # razão preço/mediana que satura o flag em 1.0 (≥2× = clássico)
MIN_AMOSTRA_PRECO = 5          # mediana só com ≥5 preços de OUTROS certames (robustez)
PISO_ARTEFATO = 0.10           # preço <10% da mediana = artefato de unidade (comparador_precos)

# Execução: Lei 14.133 art. 125 — acréscimo contratual limitado a 25%
LIMITE_ADITIVO_LEGAL = 0.25
VALOR_ADITIVO_METADE_LIMITE = 0.5

FAIXAS_ROTULO = ("BAIXO", "MEDIO", "ALTO", "EXTREMO")


def _q(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list:
    """Query tolerante a tabela ausente: fonte não coletada = INDISPONÍVEL, não crash."""
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


def _so_digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _flag(nome: str, valor: float, evidencia: str) -> dict:
    return {"flag": nome, "valor": round(min(1.0, max(0.0, valor)), 3), "evidencia": evidencia}


def _familia(flags: list[dict], fonte: str, nota: str | None = None) -> dict:
    """Fecha a família: valor = MÁXIMO dos flags apuráveis (nunca soma — §3.2 anti-dupla-contagem).
    Sem flag apurável → INDISPONÍVEL (valor None, apuravel False)."""
    d = {"apuravel": bool(flags), "valor": max((f["valor"] for f in flags), default=None),
         "flags": flags, "fonte": fonte}
    if nota:
        d["nota"] = nota
    return d


# ───────────────────────────── contexto do certame (pncp_resultado) ─────────────────────────────
def _contexto_pncp(conn: sqlite3.Connection, certame: str) -> dict:
    rows = _q(conn, "SELECT modalidade, data_pub, fornecedor_cnpj, ordem_classificacao, "
                    "valor_homologado, valor_unitario, item_descricao FROM pncp_resultado "
                    "WHERE certame=?", (certame,))
    vencedores = sorted({_so_digitos(r[2]) for r in rows
                         if r[2] and (r[3] == 1 or r[3] is None)})
    itens_vencedor = [(r[6], r[5]) for r in rows
                      if (r[3] == 1 or r[3] is None) and r[6] and r[5] and r[5] > 0]
    return {
        "tem_dado": bool(rows),
        "modalidade": next((r[0] for r in rows if r[0] is not None), None),
        "data_pub": next((r[1] for r in rows if r[1]), None),
        "vencedores": vencedores,
        "n_forn_ordem": len({r[2] for r in rows if r[2] and r[3] is not None}),
        "tem_ordem_alem_do_1o": any(r[3] is not None and r[3] > 1 for r in rows),
        "valor_total": sum(r[4] for r in rows if (r[3] == 1 or r[3] is None) and r[4]) or 0.0,
        "itens_vencedor": itens_vencedor,
    }


# ───────────────────────────────────── famílias ─────────────────────────────────────
def _f_transparencia(ctx: dict) -> dict:
    if not ctx["tem_dado"]:
        return _familia([], "pncp_resultado", "certame sem registro em pncp_resultado")
    flags = []
    mod = ctx["modalidade"]
    if mod == MODALIDADE_INEXIGIBILIDADE:
        flags.append(_flag("contratacao_direta", VALOR_FLAG_INEXIGIBILIDADE,
                           "modalidade 9 = inexigibilidade (art. 74 Lei 14.133) — sem disputa"))
    elif mod == MODALIDADE_DISPENSA:
        flags.append(_flag("contratacao_direta", VALOR_FLAG_DISPENSA,
                           "modalidade 8 = dispensa (art. 75 Lei 14.133) — sem disputa"))
    else:
        flags.append(_flag("contratacao_direta", 0.0, f"modalidade {mod} — procedimento com disputa"))
    flags.append(_flag("sem_data_publicacao", 0.0 if ctx["data_pub"] else VALOR_FLAG_SEM_DATA_PUB,
                       f"data de publicação: {ctx['data_pub'] or 'AUSENTE no registro PNCP'}"))
    return _familia(flags, "pncp_resultado")


def _f_competicao(conn: sqlite3.Connection, certame: str, ctx: dict) -> dict:
    flags = []
    forn_propostas = {r[0] for r in _q(conn, "SELECT DISTINCT fornecedor_cnpj FROM proposta_item "
                                             "WHERE certame=?", (certame,))}
    # nº de proponentes: apurável só com atas (proposta_item) ou PNCP com ordem>1 gravada
    # (registro só do vencedor NÃO prova licitante único — ver docstring)
    if forn_propostas or ctx["tem_ordem_alem_do_1o"]:
        n = max(len(forn_propostas), ctx["n_forn_ordem"])
        valor = (VALOR_LICITANTE_UNICO if n <= 1 else
                 VALOR_DOIS_LICITANTES if n == 2 else
                 VALOR_TRES_LICITANTES if n < MIN_LICITANTES_SAUDAVEL else 0.0)
        nome = "licitante_unico" if n <= 1 else "poucos_licitantes"
        flags.append(_flag(nome, valor, f"{n} proponente(s) distinto(s) "
                           f"(proposta_item={len(forn_propostas)}, pncp ordem={ctx['n_forn_ordem']})"))
    # restritividade de cláusulas (clausula_veredito casa por numero_controle_pncp — 226 na base)
    ver = _q(conn, "SELECT score_final, veredito, forca_e7, sumula FROM clausula_veredito "
                   "WHERE numero_controle_pncp=? AND score_final IS NOT NULL", (certame,))
    if ver:
        top = max(ver, key=lambda r: r[0])
        flags.append(_flag("clausula_restritiva", top[0] / 10.0,
                           f"veredito '{top[1]}' escore {top[0]}/10 (força E7: {top[2]}"
                           + (f"; {top[3]}" if top[3] else "") + ")"))
    return _familia(flags, "proposta_item + pncp_resultado + clausula_veredito")


def _f_conluio(conn: sqlite3.Connection, certame: str) -> dict:
    try:
        s = screens(conn, certame)  # já é honesto: confianca=0 quando nada era apurável
    except sqlite3.OperationalError:  # proposta_item ainda não criada = fonte não coletada
        s = None
    if not s or s["confianca"] <= 0:
        return _familia([], "screens_conluio(proposta_item)",
                        "sem lances/vetores apuráveis (screens exigem ≥3 lances)")
    ev = ", ".join(s["flags"]) if s["flags"] else "nenhum screen disparado"
    flags = [_flag("screens_conluio", s["score_conluio"],
                   f"{len(s['flags'])} screen(s) OCDE: {ev} (n_lances={s['n_lances']}, "
                   f"confianca screens={s['confianca']})")]
    return _familia(flags, "screens_conluio(proposta_item)")


def _f_fraude_cadastral(conn: sqlite3.Connection, ctx: dict) -> dict:
    if not ctx["vencedores"]:
        return _familia([], "fantasma_score + sancoes_federais",
                        "vencedor não identificado no certame")
    flags = []
    for cnpj in ctx["vencedores"]:
        fs = _q(conn, "SELECT score, classificacao FROM fantasma_score WHERE cnpj=?", (cnpj,))
        if fs:
            sc, cla = fs[0]
            flags.append(_flag("vencedor_fantasma", (sc or 0) / ESCALA_FANTASMA,
                               f"vencedor {cnpj}: fantasma_score {sc}/100 ({cla})"))
    # sanção VIGENTE À ÉPOCA da publicação (data_inicio ≤ data_pub ≤ data_fim; fim aberto conta)
    if ctx["data_pub"] and _q(conn, "SELECT 1 FROM sancoes_federais LIMIT 1"):
        sancionados = []
        for cnpj in ctx["vencedores"]:
            hit = _q(conn, "SELECT cadastro, data_inicio, data_fim FROM sancoes_federais "
                           "WHERE REPLACE(REPLACE(REPLACE(cpf_cnpj,'.',''),'/',''),'-','')=? "
                           "AND data_inicio<=? AND (data_fim IS NULL OR data_fim>=?)",
                     (cnpj, ctx["data_pub"], ctx["data_pub"]))
            if hit:
                sancionados.append((cnpj, hit[0]))
        if sancionados:
            c, (cad, ini, fim) = sancionados[0]
            flags.append(_flag("sancao_vigente_a_epoca", 1.0,
                               f"vencedor {c} com sanção {cad} vigente na publicação "
                               f"({ini} → {fim or 'aberta'})"))
        else:
            flags.append(_flag("sancao_vigente_a_epoca", 0.0,
                               "nenhum vencedor sancionado na data de publicação"))
    return _familia(flags, "fantasma_score + sancoes_federais")


def _f_preco(conn: sqlite3.Connection, certame: str, ctx: dict) -> dict:
    """Sobrepreço do VENCEDOR vs mediana do item normalizado em OUTROS certames (outlier local,
    não threshold universal — Cardinal). preco_referencia_cache (CATMAT) não é joinável (ver
    docstring do módulo)."""
    melhor: tuple[float, str] | None = None
    apuravel = False
    for desc, vu in ctx["itens_vencedor"]:
        base = _norm_item(desc)
        if not base:
            continue
        # filtra pelo item normalizado (feito em Python: _norm_item não existe em SQL)
        precos = [r[1] for r in _q(conn, "SELECT item_descricao, valor_unitario FROM pncp_resultado "
                                         "WHERE certame != ? AND valor_unitario > 0", (certame,))
                  if _norm_item(r[0] or "") == base]
        precos = sorted(precos)
        if len(precos) < MIN_AMOSTRA_PRECO:
            continue
        med = _mediana(precos)
        if not med or vu < PISO_ARTEFATO * med:
            continue  # artefato de unidade/embalagem — não comparar
        apuravel = True
        razao = vu / med
        valor = max(0.0, min(1.0, (razao - 1.0) / (SOBREPRECO_FATOR - 1.0)))
        ev = (f"item '{desc[:60]}': unitário do vencedor {vu:,.2f} = {razao:.2f}× a mediana "
              f"{med:,.2f} de {len(precos)} preços em outros certames")
        if melhor is None or valor > melhor[0]:
            melhor = (valor, ev)
    if not apuravel:
        return _familia([], "pncp_resultado.valor_unitario (mediana por item)",
                        f"sem item com ≥{MIN_AMOSTRA_PRECO} preços comparáveis em outros certames")
    return _familia([_flag("sobrepreco_vs_mediana", melhor[0], melhor[1])],
                    "pncp_resultado.valor_unitario (mediana por item)")


def _f_execucao(conn: sqlite3.Connection, certame: str, ctx: dict) -> dict:
    """Aditivos do contrato decorrente. HOJE sempre INDISPONÍVEL na base real: a chave de
    contrato_aditivo é do CONTRATO ("-2-"), não da compra ("-1-"), e não há ponte (0 joins
    verificados). A query fica pronta para quando a ponte existir."""
    rows = _q(conn, "SELECT valor_acrescido FROM contrato_aditivo WHERE numero_controle_pncp=?",
              (certame,))
    acrescido = sum(r[0] for r in rows if r and r[0])
    if not rows or not ctx["valor_total"]:
        return _familia([], "contrato_aditivo",
                        "sem vínculo compra→contrato na base (chaves PNCP distintas) — "
                        "ausência de aditivo relacionável ≠ ausência de aditivo")
    pct = acrescido / ctx["valor_total"]
    valor = (1.0 if pct > LIMITE_ADITIVO_LEGAL else
             VALOR_ADITIVO_METADE_LIMITE if pct > LIMITE_ADITIVO_LEGAL / 2 else 0.0)
    return _familia([_flag("aditivo_relevante", valor,
                           f"acréscimos somam {pct:.1%} do valor homologado "
                           f"(limite legal 25% — art. 125 Lei 14.133)")], "contrato_aditivo")


# ───────────────────────────── agregação, matriz e persistência ─────────────────────────────
def _faixa(score: float) -> str:
    return ("BAIXO" if score < FAIXA_BAIXO_MAX else "MEDIO" if score < FAIXA_MEDIO_MAX
            else "ALTO" if score < FAIXA_ALTO_MAX else "EXTREMO")


def _matriz_sv(faixa: str, confianca: float, n_drivers: int) -> dict:
    """Matriz Severidade × Verossimilhança — mesmo contrato de relatorio_direcionamento.
    _matriz_risco (escala 1-5 cada; régua do produto 1-4 baixo · 5-9 médio · 10-15 alto ·
    16-25 crítico), reimplementada mínima em dict (o original devolve HTML da ficha).
    Severidade = dano potencial (faixa do score); Verossimilhança = robustez do indício
    (nº de famílias concordantes; teto 3 com confianca <0.5 — sem dado, não passa de 'possível')."""
    sev = {"EXTREMO": 5, "ALTO": 4, "MEDIO": 3, "BAIXO": 2}[faixa]
    ver = 5 if n_drivers >= 3 else 4 if n_drivers == 2 else 3 if n_drivers == 1 else 2
    if confianca < 0.5:
        ver = min(ver, 3)
    prod = sev * ver
    nivel, acao = (("CRÍTICO", "representação com pedido de suspensão cautelar do certame")
                   if prod >= 16 else
                   ("ALTO", "diligência prioritária ao órgão; minuta de representação preparada")
                   if prod >= 10 else
                   ("MÉDIO", "diligência ordinária; reavaliar com a resposta do órgão")
                   if prod >= 5 else
                   ("BAIXO", "monitoramento; sem medida imediata"))
    return {"severidade": sev, "verossimilhanca": ver, "produto": prod, "nivel": nivel,
            "acao": acao, "regua": "1-4 baixo · 5-9 médio · 10-15 alto · 16-25 crítico"}


def calcular(certame: str, db_path=None) -> dict:
    """Calcula o Índice de Direcionamento do certame (leitura; não persiste).
    Devolve {certame, score 0-100, prioridade, faixa, confianca, familias, drivers, matriz_sv,
    valor_total, _nota}."""
    conn = _conectar_ro(db_path)
    try:
        ctx = _contexto_pncp(conn, certame)
        familias = {
            "transparencia": _f_transparencia(ctx),
            "competicao": _f_competicao(conn, certame, ctx),
            "conluio": _f_conluio(conn, certame),
            "fraude_cadastral": _f_fraude_cadastral(conn, ctx),
            "preco": _f_preco(conn, certame, ctx),
            "execucao": _f_execucao(conn, certame, ctx),
        }
    finally:
        conn.close()

    apuraveis = {f: d for f, d in familias.items() if d["apuravel"]}
    peso_total = sum(_PESOS_FAMILIA[f] for f in apuraveis)
    score = (100.0 * sum(_PESOS_FAMILIA[f] * d["valor"] for f, d in apuraveis.items()) / peso_total
             if peso_total else 0.0)
    score = round(score, 2)
    confianca = round(len(apuraveis) / len(FAMILIAS), 2)
    faixa = _faixa(score) if apuraveis else "BAIXO"

    drivers = []
    for f, d in apuraveis.items():
        if d["valor"] is not None and d["valor"] >= LIMIAR_DRIVER:
            top = max(d["flags"], key=lambda x: x["valor"])
            drivers.append({"familia": f, "flag": top["flag"], "valor": top["valor"],
                            "evidencia": top["evidencia"]})
    drivers.sort(key=lambda x: -x["valor"])

    return {
        "certame": certame,
        "score": score,
        "prioridade": round(score * math.log1p(ctx["valor_total"]), 2),
        "faixa": faixa,
        "confianca": confianca,
        "valor_total": round(ctx["valor_total"], 2),
        "familias": familias,
        "drivers": drivers,
        "matriz_sv": _matriz_sv(faixa, confianca, len(drivers)),
        "_nota": ("Índice contextual de PRIORIZAÇÃO interna (§3.2 BENCHMARKS-EXTERNOS): indício "
                  "≠ acusação; presume-se a legitimidade do certame. Família INDISPONÍVEL não "
                  "pontua nem zera — reduz a confiança. Pesos iniciais dos benchmarks; "
                  "calibração local pendente."),
    }


def garantir_tabela(conn: sqlite3.Connection) -> None:
    """Cria `certame_indice` (aditivo, idempotente — padrão editais/db.py)."""
    conn.execute(DDL_CERTAME_INDICE)


# Espelho do schema REAL de `caso` no compliance.db (PRAGMA verificado em 2026-07-19);
# IF NOT EXISTS = aditivo: em produção a tabela já existe, em DB de teste é criada igual.
DDL_CASO = """CREATE TABLE IF NOT EXISTS caso (
  id TEXT PRIMARY KEY,
  alvo TEXT,
  tipo_achado TEXT,
  titulo TEXT,
  resumo TEXT,
  risco_achado REAL,
  risco_punicao REAL,
  economia_potencial REAL,
  status TEXT DEFAULT 'novo',
  evidencia_ids TEXT,
  criado_em TEXT,
  atualizado_em TEXT,
  nota TEXT
)"""

FAIXAS_CASO = ("ALTO", "EXTREMO")   # faixas que abrem caso de fiscalização (Task 4.5)


def gravar_caso_se_alto(resultado: dict, db_path=None) -> bool:
    """Abre um CASO de fiscalização quando o índice fecha em faixa ALTO/EXTREMO.

    Idempotente por (alvo, tipo_achado='direcionamento'): recomputar o índice nunca
    duplica o caso nem regride o `status` já em andamento (novo→apurando→...).
    `risco_punicao`/`economia_potencial` ficam NULL — não há fonte apurável aqui e
    INDISPONÍVEL ≠ 0. Devolve True só quando um caso NOVO foi gravado."""
    if resultado.get("faixa") not in FAIXAS_CASO:
        return False
    certame = resultado["certame"]
    conn = conectar(db_path)
    try:
        conn.execute(DDL_CASO)
        ja = conn.execute("SELECT 1 FROM caso WHERE alvo=? AND tipo_achado='direcionamento'",
                          (certame,)).fetchone()
        if ja:
            return False
        drivers = resultado.get("drivers") or []
        titulo = (f"Índice de Direcionamento {resultado['faixa']} "
                  f"({resultado['score']:.0f}/100) — certame {certame}")
        resumo = (f"Score {resultado['score']:.1f}/100 (confiança {resultado['confianca']:.2f}); "
                  f"{len(drivers)} driver(s): "
                  + ("; ".join(f"{d['familia']}/{d['flag']}" for d in drivers) or "nenhum")
                  + ". Indício de priorização interna — não é acusação.")
        conn.execute(
            "INSERT INTO caso (id, alvo, tipo_achado, titulo, resumo, risco_achado, "
            "risco_punicao, economia_potencial, status, evidencia_ids, criado_em, "
            "atualizado_em, nota) VALUES (?,?,?,?,?,?,NULL,NULL,'novo',?,"
            "datetime('now'),datetime('now'),?)",
            (f"direcionamento:{certame}", certame, "direcionamento", titulo, resumo,
             resultado["score"], json.dumps(drivers, ensure_ascii=False),
             resultado.get("_nota") or ""))
        conn.commit()
        return True
    finally:
        conn.close()


def calcular_e_persistir(certame: str, db_path=None, gravar_caso: bool = True) -> dict:
    """calcular() + UPSERT em certame_indice (gerado_em = agora); faixa ALTO/EXTREMO
    abre caso de fiscalização (idempotente — desligável com gravar_caso=False)."""
    r = calcular(certame, db_path)
    conn = conectar(db_path)
    try:
        garantir_tabela(conn)
        conn.execute(
            "INSERT OR REPLACE INTO certame_indice (certame, score, prioridade, faixa, confianca, "
            "familias_json, drivers_json, gerado_em) VALUES (?,?,?,?,?,?,?,datetime('now'))",
            (r["certame"], r["score"], r["prioridade"], r["faixa"], r["confianca"],
             json.dumps(r["familias"], ensure_ascii=False),
             json.dumps(r["drivers"], ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()
    if gravar_caso:
        gravar_caso_se_alto(r, db_path)
    return r


def _certames_com_contexto(db_path=None) -> list[str]:
    """Certames com algum sinal contextual coletado (edital, propostas ou vereditos) — o
    universo útil do índice; rodar sobre os 40k+ certames crus do PNCP seria só transparencia."""
    conn = _conectar_ro(db_path)
    try:
        out: set[str] = set()
        for sql in ("SELECT DISTINCT numero_controle_pncp FROM edital_documento",
                    "SELECT DISTINCT certame FROM proposta_item",
                    "SELECT DISTINCT numero_controle_pncp FROM clausula_veredito "
                    "WHERE numero_controle_pncp IS NOT NULL"):
            out.update(r[0] for r in _q(conn, sql) if r[0])
        return sorted(out)
    finally:
        conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Índice de Direcionamento de Certame (0-100)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--certame", help="numero de controle PNCP do certame")
    g.add_argument("--todos", action="store_true",
                   help="serial sobre certames com contexto coletado (edital/propostas/vereditos)")
    ap.add_argument("--db", default=None, help="caminho alternativo do compliance.db")
    args = ap.parse_args(argv)
    alvos = [args.certame] if args.certame else _certames_com_contexto(args.db)
    for c in alvos:
        r = calcular_e_persistir(c, args.db)
        print(f"{c}  score={r['score']:.1f} ({r['faixa']})  confianca={r['confianca']} "
              f"prioridade={r['prioridade']:.1f}  drivers={len(r['drivers'])}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
