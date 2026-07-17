# -*- coding: utf-8 -*-
"""cruzamentos_intel — os 3 cruzamentos de inteligência pedidos pelo dono (2026-07-17):

1. SANCIONADAS CONTRATADAS — empresas em sanção impeditiva (CEIS/CNEP, `sancoes_federais`)
   que receberam pagamento do Estado (OB SIAFE) ou venceram certame (PNCP), com o teste
   temporal "À ÉPOCA": o ato (OB/homologação) caiu DENTRO da vigência [data_inicio, data_fim]?
   Sanção posterior ao ato NÃO macula o ato (mesma regra do nucleo/adaptador_db).

2. PERDEDORAS CONTUMAZES ("nunca ganharam") — licitantes que aparecem em ≥K atas e nunca
   vencem (candidatas a proposta de cobertura/OCDE), com quem "perdem junto" (beneficiário
   provável). Fonte: corpus de atas (`edital_documento`) → rodizio_grafo.detectar_padroes.

3. FANTASMAS EM ESCALA — score /fantasma (8 sinais determinísticos, empresa_fantasma) aplicado
   ao conjunto-ALVO (vencedoras de captura/rodízio + perdedoras contumazes + sancionadas
   contratadas + top favorecidos SIAFE), persistido em `fantasma_score`. Sem cadastro local
   → `sem_cadastro` (INDISPONÍVEL ≠ 0; a fila de enriquecimento resolve depois).

Tudo determinístico (sem IA). Indício ≠ acusação — cada saída carrega a ressalva.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = str(_REPO / "data" / "compliance.db")
_CACHE_DIR = _REPO / "data" / "cache"

logger = logging.getLogger(__name__)

# mesma régua do nucleo/adaptador_db._tem_sancao_vigente: só sanção IMPEDITIVA conta
_SQL_IMPEDITIVA = ("(lower(categoria) LIKE '%imped%' OR lower(categoria) LIKE '%suspens%' "
                   "OR lower(categoria) LIKE '%inid%' OR lower(categoria) LIKE '%proib%' "
                   "OR lower(categoria) LIKE '%declara%')")

# OB SIAFE guarda data DD/MM/AAAA (string) — converter p/ ISO na consulta
_OB_ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"

RESSALVA = ("Indício para apuração interna, não acusação. Sanção impeditiva vigente à época do ato "
            "é vedação legal (Lei 14.133, art. 156 §1º; Lei 8.666, arts. 87-88) — confirmar no "
            "cadastro-fonte (Portal da Transparência/CGU) antes de qualquer uso externo.")


# Teto de dispensa de licitação por ano (Lei 14.133 art. 75-II, compras/serviços comuns; valores
# atualizados por decreto). Abaixo dele o gestor pode contratar SEM licitação — o incentivo a
# "fatiar" a despesa para caber embaixo é o vetor clássico de fracionamento (Lei 14.133 art. 75 §1º).
_TETO_DISPENSA = {2021: 50000.00, 2022: 50000.00, 2023: 52707.00,
                  2024: 59906.02, 2025: 59906.02, 2026: 59906.02}
_TETO_DEFAULT = 59906.02


def _ro(db_path: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path or _DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    return con


# ── 1. SANCIONADAS CONTRATADAS ───────────────────────────────────────────────

def sancionadas_contratadas(db_path: str | None = None, min_valor: float = 0.0) -> dict:
    """Cruza sanções impeditivas × OB SIAFE (Estado) × vitórias PNCP (todas as esferas).
    Por empresa: sanções, pagamentos/vitórias TOTAIS e os DURANTE a vigência ("à época")."""
    con = _ro(db_path)
    try:
        # sanções impeditivas de PJ (14 dígitos; CPF sancionado não contrata como empresa)
        sanc: dict[str, list] = {}
        for r in con.execute(
                f"SELECT cpf_cnpj, nome, cadastro, categoria, data_inicio, data_fim, orgao "
                f"FROM sancoes_federais WHERE length(cpf_cnpj)=14 AND {_SQL_IMPEDITIVA}"):
            sanc.setdefault(r["cpf_cnpj"], []).append(dict(r))

        achados: dict[str, dict] = {}

        def _base(cnpj: str, nome: str) -> dict:
            return achados.setdefault(cnpj, {
                "cnpj": cnpj, "nome": nome, "sancoes": sanc.get(cnpj, []),
                "estado": {"obs": 0, "valor": 0.0, "obs_durante": 0, "valor_durante": 0.0,
                           "exemplos_durante": []},
                "pncp": {"vitorias": 0, "valor": 0.0, "vitorias_durante": 0, "valor_durante": 0.0,
                         "esferas": {}, "exemplos_durante": []},
            })

        # Estado: OBs SIAFE pagas a CNPJ sancionado (total e durante a vigência)
        q_ob = (f"SELECT credor, nome_credor, numero_ob, valor, {_OB_ISO} AS dt "
                f"FROM ob_orcamentaria_siafe WHERE length(credor)=14 AND credor IN "
                f"({','.join('?' * len(sanc))})")
        if sanc:
            for r in con.execute(q_ob, list(sanc)):
                a = _base(r["credor"], r["nome_credor"])
                a["estado"]["obs"] += 1
                a["estado"]["valor"] += r["valor"] or 0.0
                for s in a["sancoes"]:
                    ini, fim = s.get("data_inicio") or "0000", s.get("data_fim") or "9999"
                    if ini <= r["dt"] <= fim:
                        a["estado"]["obs_durante"] += 1
                        a["estado"]["valor_durante"] += r["valor"] or 0.0
                        if len(a["estado"]["exemplos_durante"]) < 5:
                            a["estado"]["exemplos_durante"].append(
                                {"ob": r["numero_ob"], "data": r["dt"], "valor": r["valor"],
                                 "sancao": s["cadastro"], "vigencia": f"{ini}→{fim}"})
                        break

        # PNCP: vitórias homologadas de CNPJ sancionado (com esfera oficial do ente)
        try:
            from compliance_agent.collectors.pncp_resultados import (
                classificar_esfera, esferas_por_ente)
            oficial = esferas_por_ente(con)
        except Exception:
            oficial, classificar_esfera = {}, None
        if sanc:
            q_pncp = ("SELECT certame, orgao_cnpj, orgao_nome, unidade_nome, municipio, "
                      "fornecedor_cnpj, fornecedor_nome, data_pub, SUM(valor_homologado) v "
                      "FROM pncp_resultado WHERE ordem_classificacao=1 AND fornecedor_cnpj IN "
                      f"({','.join('?' * len(sanc))}) GROUP BY certame, fornecedor_cnpj")
            for r in con.execute(q_pncp, list(sanc)):
                a = _base(r["fornecedor_cnpj"], r["fornecedor_nome"])
                esf = classificar_esfera(dict(r), oficial) if classificar_esfera else "?"
                a["pncp"]["vitorias"] += 1
                a["pncp"]["valor"] += r["v"] or 0.0
                a["pncp"]["esferas"][esf] = a["pncp"]["esferas"].get(esf, 0) + 1
                dt = (r["data_pub"] or "")[:10]
                for s in a["sancoes"]:
                    ini, fim = s.get("data_inicio") or "0000", s.get("data_fim") or "9999"
                    if dt and ini <= dt <= fim:
                        a["pncp"]["vitorias_durante"] += 1
                        a["pncp"]["valor_durante"] += r["v"] or 0.0
                        if len(a["pncp"]["exemplos_durante"]) < 5:
                            a["pncp"]["exemplos_durante"].append(
                                {"certame": r["certame"], "orgao": r["unidade_nome"] or r["orgao_nome"],
                                 "esfera": esf, "data": dt, "valor": r["v"],
                                 "sancao": s["cadastro"], "vigencia": f"{ini}→{fim}"})
                        break

        lista = [a for a in achados.values()
                 if (a["estado"]["valor"] + a["pncp"]["valor"]) >= min_valor]
        # gravidade primeiro: quem tem ato DURANTE a sanção; depois por valor
        lista.sort(key=lambda a: (-(a["estado"]["valor_durante"] + a["pncp"]["valor_durante"]),
                                  -(a["estado"]["valor"] + a["pncp"]["valor"])))
        n_epoca = sum(1 for a in lista
                      if a["estado"]["obs_durante"] or a["pncp"]["vitorias_durante"])
        return {"ok": True, "empresas": lista, "n": len(lista), "n_a_epoca": n_epoca,
                "ressalva": RESSALVA}
    finally:
        con.close()


# ── 2. PERDEDORAS CONTUMAZES (nunca ganharam) ────────────────────────────────

def perdedoras_contumazes(db_path: str | None = None, min_certames: int = 3,
                          limite_atas: int = 8000) -> dict:
    """Licitantes que participam de ≥K certames (nas atas) e NUNCA vencem — candidatas a
    proposta de cobertura. Enriquecidas com nome e com quem 'perdem junto'."""
    from compliance_agent.rodizio_grafo import analisar_atas, coletar_atas_do_corpus
    atas = coletar_atas_do_corpus(db_path or _DB, limite=limite_atas)
    res = analisar_atas(atas, min_certames=min_certames)
    con = _ro(db_path)
    try:
        nomes: dict[str, str] = {}
        for r in con.execute("SELECT DISTINCT fornecedor_cnpj, fornecedor_nome FROM pncp_resultado "
                             "WHERE fornecedor_nome IS NOT NULL"):
            nomes.setdefault(r["fornecedor_cnpj"], r["fornecedor_nome"])
        for r in con.execute("SELECT favorecido_cpf, favorecido_nome FROM favorecido_resumo"):
            nomes.setdefault(r["favorecido_cpf"], r["favorecido_nome"])
    finally:
        con.close()

    def _fmt(c: str) -> str:
        return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}" if len(c) == 14 else c

    cobertura = []
    for c in res.get("cobertura", []):
        cid = c["licitante"]
        cobertura.append({
            "cnpj": cid, "cnpj_fmt": _fmt(cid), "nome": nomes.get(cid, "—"),
            "participou": c["participou"], "venceu": 0,
            "perde_junto_com": [{"cnpj": _fmt(co), "nome": nomes.get(co, "—"), "vezes": n}
                                for co, n in c.get("co_frequentes", [])],
        })
    return {"ok": True, "perdedoras": cobertura, "n": len(cobertura),
            "cobertura_extracao": res.get("cobertura_extracao", {}),
            "explicacao": ("Empresa que compete 'sempre' e nunca vence é o perfil clássico de "
                           "PROPOSTA DE COBERTURA (OCDE bid rigging): existe para dar aparência "
                           "de disputa e legitimar o vencedor combinado. Quanto mais vezes perde "
                           "junto do MESMO vencedor, mais forte o indício."),
            "ressalva": "Indício estatístico das atas — corroborar QSA, endereços e propostas. "
                        "Indício ≠ acusação; pode haver azar competitivo legítimo."}


# ── 3. FANTASMAS EM ESCALA ───────────────────────────────────────────────────

def init_fantasma_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS fantasma_score (
            cnpj          TEXT PRIMARY KEY,
            razao_social  TEXT,
            score         INTEGER,
            classificacao TEXT,               -- alto | medio | baixo | sem_cadastro
            sinais_json   TEXT,
            origem        TEXT,               -- por que entrou no alvo (captura/cover/sancionada/top_favorecido)
            avaliado_em   TEXT DEFAULT (datetime('now'))
        )""")
    con.commit()


def alvos_fantasma(db_path: str | None = None, top_favorecidos: int = 300) -> dict[str, str]:
    """Conjunto-ALVO {cnpj: origem}: vencedoras de captura/rodízio + perdedoras contumazes +
    sancionadas contratadas + top favorecidos SIAFE por valor."""
    alvos: dict[str, str] = {}
    con = _ro(db_path)
    try:
        from compliance_agent.collectors.pncp_resultados import conluio_enriquecido
        pad = conluio_enriquecido(con, min_certames=4)
        for cap in pad.get("captura", []):
            alvos.setdefault(cap["vencedor"], "captura")
        for rod in pad.get("rodizio_vencedores", []):
            for c in rod.get("grupo", []):
                alvos.setdefault(c, "rodizio")
        for r in con.execute(
                "SELECT favorecido_cpf c, SUM(total_pago) t FROM favorecido_resumo "
                "WHERE length(favorecido_cpf)=14 GROUP BY 1 ORDER BY t DESC LIMIT ?",
                (top_favorecidos,)):
            alvos.setdefault(r["c"], "top_favorecido")
    except Exception as exc:
        logger.warning("alvos de conluio/favorecidos parciais: %s", exc)
    finally:
        con.close()
    try:
        for p in perdedoras_contumazes(db_path).get("perdedoras", []):
            alvos.setdefault(p["cnpj"], "perdedora_contumaz")
    except Exception as exc:
        logger.warning("perdedoras contumazes fora do alvo: %s", exc)
    try:
        for e in sancionadas_contratadas(db_path).get("empresas", []):
            alvos.setdefault(e["cnpj"], "sancionada_contratada")
    except Exception as exc:
        logger.warning("sancionadas fora do alvo: %s", exc)
    return alvos


def avaliar_fantasmas(db_path: str | None = None, alvos: dict[str, str] | None = None) -> dict:
    """Aplica os 8 sinais (/fantasma) ao conjunto-alvo e persiste em fantasma_score.
    CNPJ sem cadastro local → 'sem_cadastro' (não é 'baixo'; INDISPONÍVEL ≠ 0)."""
    from compliance_agent.empresa_fantasma import avaliar_cnpj
    from compliance_agent.nucleo.telegram_nucleo import _sessao
    alvos = alvos or alvos_fantasma(db_path)
    wcon = sqlite3.connect(db_path or _DB, timeout=60)
    wcon.execute("PRAGMA busy_timeout=60000")
    init_fantasma_schema(wcon)
    session = _sessao()
    n_aval = n_sem = 0
    try:
        for cnpj, origem in alvos.items():
            try:
                r = avaliar_cnpj(session, cnpj)
            except Exception as exc:
                logger.debug("avaliar_cnpj falhou p/ %s: %s", cnpj, exc)
                r = None
            # sem linha em `empresas` = sem cadastro → não dá para afirmar score
            tem_cadastro = bool(r and (r.get("razao_social") or any(
                s.get("id") not in (None, "sancionada") for s in r.get("sinais", []))))
            if r and tem_cadastro:
                wcon.execute(
                    "INSERT OR REPLACE INTO fantasma_score(cnpj,razao_social,score,classificacao,"
                    "sinais_json,origem) VALUES(?,?,?,?,?,?)",
                    (cnpj, r.get("razao_social"), r.get("score"), r.get("classificacao"),
                     json.dumps(r.get("sinais", []), ensure_ascii=False), origem))
                n_aval += 1
            else:
                wcon.execute(
                    "INSERT OR REPLACE INTO fantasma_score(cnpj,razao_social,score,classificacao,"
                    "sinais_json,origem) VALUES(?,?,NULL,'sem_cadastro','[]',?)",
                    (cnpj, (r or {}).get("razao_social"), origem))
                n_sem += 1
        wcon.commit()
    finally:
        session.close()
        wcon.close()
    return {"ok": True, "avaliados": n_aval, "sem_cadastro": n_sem, "alvo": len(alvos)}


def ranking_fantasmas(db_path: str | None = None, limite: int = 50) -> dict:
    """Lê fantasma_score (gerado por avaliar_fantasmas/tools.intel_sweep) — ranking p/ o painel."""
    con = _ro(db_path)
    try:
        try:
            rows = [dict(r) for r in con.execute(
                "SELECT cnpj, razao_social, score, classificacao, sinais_json, origem, avaliado_em "
                "FROM fantasma_score ORDER BY (score IS NULL), score DESC LIMIT ?", (limite,))]
        except sqlite3.OperationalError:
            return {"ok": False, "erro": "fantasma_score ainda não gerado — rodar tools/intel_sweep.py"}
        sem = con.execute("SELECT COUNT(*) FROM fantasma_score WHERE classificacao='sem_cadastro'").fetchone()[0]
        tot = con.execute("SELECT COUNT(*) FROM fantasma_score").fetchone()[0]
        for r in rows:
            r["sinais"] = json.loads(r.pop("sinais_json") or "[]")
        return {"ok": True, "empresas": rows, "total_alvo": tot, "sem_cadastro": sem,
                "explicacao": ("Score 0-100 por 8 sinais objetivos (situação cadastral irregular, "
                               "capital incompatível, endereço-ninho, endereço residencial, aberta às "
                               "vésperas do contrato, sócio único + capital baixo, CNAE incompatível, "
                               "sanção CEIS/CNEP). 'sem_cadastro' = Receita ainda não consultada — "
                               "não significa regular NEM fantasma."),
                "ressalva": "Triagem determinística; indício ≠ acusação."}
    finally:
        con.close()


# ── cache p/ endpoints (perdedoras varre 8k atas — não roda no request) ──────

def fracionamento(db_path: str | None = None, min_obs: int = 5, min_colado: int = 3,
                  banda: float = 0.85, limite: int = 120) -> dict:
    """Possível FRACIONAMENTO de despesa: mesmo favorecido + mesma UG + mesmo MÊS com muitas OBs,
    várias delas "coladas no teto" de dispensa (85-100% do limite do ano) — padrão de fatiar a
    compra para caber embaixo do limite e fugir da licitação (Lei 14.133 art. 75 §1º).
    Ordena pela CONCENTRAÇÃO colada no teto (separa dodging deliberado de fornecimento contínuo:
    utilidade/combustível tem valores variados, baixa concentração)."""
    con = _ro(db_path)
    try:
        iso_mes = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)"
        ano = "CAST(substr(data_emissao,7,4) AS INT)"
        # teto do ano via CASE (SQLite não tem dict); banda = 85% do teto
        casos_teto = " ".join(f"WHEN {a} THEN {t}" for a, t in _TETO_DISPENSA.items())
        teto_expr = f"(CASE {ano} {casos_teto} ELSE {_TETO_DEFAULT} END)"
        # favorecido que é ENTE PÚBLICO = repasse/transferência (fundo-a-fundo, parcelas iguais),
        # não compra fatiada — fora do detector (senão vira falso-positivo).
        publico = ("nome_credor NOT LIKE '%FUNDO%' AND nome_credor NOT LIKE '%PREFEITURA%' "
                   "AND nome_credor NOT LIKE '%MUNICIPIO%' AND nome_credor NOT LIKE '%MUNICÍPIO%' "
                   "AND nome_credor NOT LIKE '%SECRETARIA%' AND nome_credor NOT LIKE '%C_MARA%' "
                   "AND nome_credor NOT LIKE '%TRIBUNAL%' AND nome_credor NOT LIKE '%INSTITUTO DE PREV%' "
                   "AND nome_credor NOT LIKE '%ESTADO DO RIO%' AND nome_credor NOT LIKE '%DEFENSORIA%'")
        q = f"""
        SELECT credor, MAX(nome_credor) nome, ug_emitente, {iso_mes} mes,
               COUNT(*) n, SUM(valor) soma, MAX(valor) maior,
               SUM(CASE WHEN valor >= {banda}*{teto_expr} AND valor < {teto_expr} THEN 1 ELSE 0 END) n_colado,
               MAX({teto_expr}) teto
        FROM ob_orcamentaria_siafe
        WHERE length(credor)=14 AND valor>0 AND valor < {teto_expr} AND {publico}
        GROUP BY credor, ug_emitente, {iso_mes}
        HAVING n >= ? AND n_colado >= ?
        ORDER BY (CAST(n_colado AS REAL)/n) DESC, soma DESC
        LIMIT ?"""
        rows = [dict(r) for r in con.execute(q, (min_obs, min_colado, limite))]
        for r in rows:
            r["concentracao"] = round(r["n_colado"] / r["n"], 2) if r["n"] else 0
            r["cnpj_fmt"] = (f"{r['credor'][:2]}.{r['credor'][2:5]}.{r['credor'][5:8]}/"
                             f"{r['credor'][8:12]}-{r['credor'][12:]}") if len(r["credor"] or "") == 14 else r["credor"]
        # total (sem limite) p/ KPI
        total = con.execute(f"""SELECT COUNT(*) FROM (
            SELECT credor FROM ob_orcamentaria_siafe
            WHERE length(credor)=14 AND valor>0 AND valor < {teto_expr} AND {publico}
            GROUP BY credor, ug_emitente, {iso_mes}
            HAVING COUNT(*) >= ? AND
              SUM(CASE WHEN valor >= {banda}*{teto_expr} AND valor < {teto_expr} THEN 1 ELSE 0 END) >= ?)""",
            (min_obs, min_colado)).fetchone()[0]
        return {"ok": True, "grupos": rows, "n": total, "mostrados": len(rows),
                "explicacao": ("Mesmo favorecido, mesma unidade gestora e mesmo mês, com várias OBs "
                               "logo abaixo do teto de dispensa de licitação. É o padrão de FATIAR a "
                               "compra para não licitar (Lei 14.133 art. 75 §1º veda). Quanto maior a "
                               "'concentração' (% de OBs coladas no teto), mais deliberado o indício — "
                               "fornecimento contínuo legítimo tem valores variados, concentração baixa."),
                "ressalva": ("OB é PAGAMENTO, não empenho/contrato — o fracionamento se prova no "
                             "processo de contratação. Cruzar com os empenhos/processos do mês antes de "
                             "concluir; fornecimento contínuo (água, energia, combustível) pode explicar "
                             "o volume. Indício ≠ acusação.")}
    finally:
        con.close()


def _norm_item(desc: str) -> str:
    """Normaliza a descrição do item p/ agrupar compras comparáveis: minúsculas, sem acento,
    sem plural simples, sem pontuação/números soltos. 'Ventiladores' e 'VENTILADOR' → 'ventilador'."""
    import unicodedata
    s = unicodedata.normalize("NFKD", (desc or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = []
    for t in s.split():
        if len(t) < 3 or t.isdigit():
            continue
        t = re.sub(r"(es|s)$", "", t) if len(t) > 4 else t  # plural simples
        toks.append(t)
    return " ".join(sorted(set(toks)))  # ordem-insensível: "caneta azul" == "azul caneta"


def _mediana(xs: list) -> float:
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def sobrepreco(db_path: str | None = None, min_amostra: int = 5, min_certames: int = 4,
               fator: float = 2.0, limite: int = 120) -> dict:
    """Sobrepreço por MEDIANA de item: agrupa compras pela descrição normalizada do item
    (mesmo produto entre órgãos) e sinaliza quem pagou preço UNITÁRIO muito acima da mediana do
    grupo (≥ `fator`× a mediana E fora da banda robusta mediana+3·MAD). Fonte: valorUnitarioHomologado
    do PNCP. Robusto a outlier (mediana/MAD, não média).

    Guarda anti-falso-positivo: o grupo precisa abranger ≥`min_certames` CERTAMES distintos — senão
    a 'mediana' seria só a variedade de produtos dentro de um mesmo pregão sob rótulo genérico
    (ex.: esteira e halteres ambos como 'Aparelho de Acondicionamento Físico'). E o achado precisa
    ser de um certame DIFERENTE da maioria (compara compras independentes, não itens do mesmo lote)."""
    con = _ro(db_path)
    try:
        rows = con.execute(
            "SELECT item_descricao d, unidade_medida un, valor_unitario vu, certame, orgao_nome, "
            "unidade_nome, fornecedor_cnpj, fornecedor_nome, municipio, data_pub "
            "FROM pncp_resultado WHERE ordem_classificacao=1 AND valor_unitario>0 "
            "AND item_descricao IS NOT NULL AND length(item_descricao)>=3").fetchall()
        grupos: dict[str, list] = {}
        for r in rows:
            chave = _norm_item(r["d"])
            if not chave:
                continue
            grupos.setdefault(chave, []).append(r)
        achados = []
        n_grupos_validos = 0
        for chave, itens in grupos.items():
            precos = [r["vu"] for r in itens]
            n_certames = len({r["certame"] for r in itens})
            # exige amostra E diversidade de certames (compras independentes, não 1 lote genérico)
            if len(precos) < min_amostra or n_certames < min_certames:
                continue
            med = _mediana(precos)
            if med <= 0:
                continue
            mad = _mediana([abs(p - med) for p in precos]) or (med * 0.1)
            n_grupos_validos += 1
            # a mediana só é confiável se a maioria dos certames fica perto dela: exige que
            # ≥60% dos certames distintos tenham preço ≤ 2× mediana (senão o grupo é heterogêneo).
            base = len({r["certame"] for r in itens if r["vu"] <= 2 * med})
            if base < 0.6 * n_certames:
                continue
            for r in itens:
                p = r["vu"]
                z = (p - med) / (1.4826 * mad) if mad else 0  # z-score robusto (Iglewicz/Nigrini)
                if p >= fator * med and z >= 3.5:
                    achados.append({
                        "item": r["d"], "unidade_medida": r["un"], "grupo": chave,
                        "preco": p, "mediana": round(med, 2), "razao": round(p / med, 1),
                        "z_robusto": round(z, 1), "amostra": len(precos), "certames": n_certames,
                        "orgao": r["unidade_nome"] or r["orgao_nome"], "municipio": r["municipio"],
                        "fornecedor": r["fornecedor_nome"], "fornecedor_cnpj": r["fornecedor_cnpj"],
                        "certame": r["certame"], "data": (r["data_pub"] or "")[:10],
                        "sobrepreco_est": round(p - med, 2)})
        achados.sort(key=lambda a: -a["razao"])
        return {"ok": True, "achados": achados[:limite], "n": len(achados),
                "grupos_comparaveis": n_grupos_validos, "itens_com_preco": len(rows),
                "explicacao": ("Mesmo item (descrição normalizada) comprado por vários órgãos: "
                               "sinaliza quem pagou preço UNITÁRIO muito acima da mediana do grupo "
                               "(≥ 2× a mediana e fora de mediana+3·MAD, medida robusta a outliers). "
                               "Fonte: preço unitário homologado do PNCP."),
                "ressalva": ("Itens com MESMO nome podem diferir em marca, especificação, embalagem ou "
                             "quantidade — a descrição do PNCP é curta. Confirmar o termo de referência "
                             "antes de concluir sobrepreço. Indício ≠ acusação.")}
    finally:
        con.close()


def _beneficios_vinculo_resumo() -> dict:
    """Resumo do cruzamento comissionados/servidores PCRJ × benefício social DURANTE o vínculo
    (pericia_beneficios.analisar() — cruza 7,3 mi de registros; NUNCA rodar no request HTTP)."""
    from compliance_agent.pcrj import pericia_beneficios as PB
    r = PB.analisar()
    regs = sorted(r.get("registros", []), key=lambda x: -x.get("n_meses", 0))
    casos = [{k: x.get(k) for k in ("nome", "poder", "orgao", "cargo", "vinculo", "partido",
                                    "beneficios_str", "desde", "ate", "n_meses", "ainda_recebe",
                                    "certeza", "situacao", "natureza")} for x in regs[:300]]
    return {"ok": True, "n_casos": len(regs), "casos": casos,
            "resumo": {k: r.get(k) for k in ("n_alta", "n_media", "n_nomeados", "n_nao_nomeados",
                                             "n_vinculo_indet", "n_inativos", "n_bpc", "n_bf",
                                             "n_ab", "n_ae", "n_ainda", "ultima",
                                             "cobertura_folha", "cobertura_benef")},
            "explicacao": ("Benefício social recebido NO MESMO MÊS em que a pessoa tinha vínculo "
                           "remunerado com a Prefeitura/Câmara do Rio — incompatibilidade de renda a "
                           "apurar. Meses fora da janela de vínculo NÃO contam (fairness); homônimos "
                           "são eliminados por município+fragmento de CPF."),
            "ressalva": "Indício por competência (mês). Confirmar CPF completo antes de citar. "
                        "Indício ≠ acusação."}


def gerar_cache_intel(db_path: str | None = None) -> dict:
    """Materializa os cruzamentos pesados em data/cache/*.json (o painel lê em ms)."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for nome, fn in (("sancionadas_contratadas", lambda: sancionadas_contratadas(db_path)),
                     ("perdedoras_contumazes", lambda: perdedoras_contumazes(db_path)),
                     ("beneficios_vinculo", _beneficios_vinculo_resumo)):
        try:
            d = fn()
            (_CACHE_DIR / f"{nome}.json").write_text(
                json.dumps(d, ensure_ascii=False), encoding="utf-8")
            out[nome] = {"ok": d.get("ok"), "n": d.get("n", d.get("n_casos"))}
        except Exception as exc:
            logger.warning("cache %s falhou: %s", nome, exc)
            out[nome] = {"ok": False, "erro": str(exc)}
    return out


def ler_cache_intel(nome: str) -> dict | None:
    try:
        p = _CACHE_DIR / f"{nome}.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["gerado_em"] = __import__("datetime").datetime.fromtimestamp(
            p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        return d
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "cache"
    if cmd == "cache":
        print(json.dumps(gerar_cache_intel(), ensure_ascii=False, indent=1))
    elif cmd == "fantasmas":
        print(json.dumps(avaliar_fantasmas(), ensure_ascii=False, indent=1))
    elif cmd == "sancionadas":
        d = sancionadas_contratadas()
        print(f"{d['n']} empresas ({d['n_a_epoca']} com ato À ÉPOCA da sanção)")
        for e in d["empresas"][:10]:
            print(f"  {e['cnpj']} {e['nome'][:40]:40} estado_durante=R${e['estado']['valor_durante']:,.2f} "
                  f"pncp_durante={e['pncp']['vitorias_durante']}")
    elif cmd == "perdedoras":
        d = perdedoras_contumazes()
        print(f"{d['n']} perdedoras contumazes")
        for p in d["perdedoras"][:10]:
            print(f"  {p['cnpj_fmt']} {p['nome'][:40]:40} participou={p['participou']}")
    elif cmd == "fracionamento":
        d = fracionamento()
        print(f"{d['n']} grupos com possível fracionamento (colado no teto)")
        for g in d["grupos"][:12]:
            print(f"  {(g['nome'] or '')[:26]:26} UG{g['ug_emitente']} {g['mes']} "
                  f"{g['n_colado']}/{g['n']} colados ({int(g['concentracao']*100)}%) soma R${g['soma']:,.2f}")
    elif cmd == "sobrepreco":
        d = sobrepreco()
        print(f"itens com preço unitário: {d['itens_com_preco']} | grupos comparáveis: "
              f"{d['grupos_comparaveis']} | achados: {d['n']}")
        for a in d["achados"][:12]:
            print(f"  {a['item'][:34]:34} R${a['preco']:>10,.2f} vs med R${a['mediana']:>9,.2f} "
                  f"({a['razao']}x, n={a['amostra']}) — {(a['orgao'] or '')[:26]}")
