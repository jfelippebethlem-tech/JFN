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


def aditivos_estouro(db_path: str | None = None, limite: int = 120) -> dict:
    """Aditivos que estouram o limite legal de acréscimo (Lei 14.133 art. 125; Lei 8.666 art. 65 §1º
    — 25% p/ compras/serviços/obras, 50% p/ reforma). Usa pcrj_contratos (valor_inicial × valor_global)
    e cruza com contrato_aditivo p/ separar ACRÉSCIMO real de reajuste (qualif_acrescimo). Também
    marca CHANGE ORDERS EM SÉRIE (≥3 aditivos — red-flag OCDE/Banco Mundial), mesmo sem estouro de valor."""
    con = _ro(db_path)
    try:
        # acréscimos reais (não reajuste) por contrato, do contrato_aditivo (fonte granular)
        acresc = {}
        try:
            for r in con.execute("SELECT numero_controle_pncp c, SUM(valor_acrescido) v "
                                 "FROM contrato_aditivo WHERE qualif_acrescimo='1' AND valor_acrescido>0 "
                                 "GROUP BY numero_controle_pncp"):
                acresc[r["c"]] = r["v"]
        except sqlite3.OperationalError:
            pass
        # sanity: exclui valor_global lixo (> R$ 1 bi quase sempre é erro de coleta do PNCP)
        rows = con.execute(
            "SELECT numero_controle_pncp cc, fornecedor_nome, fornecedor_documento, orgao_nome, "
            "unidade, objeto, valor_inicial vi, valor_global vg, num_aditivos, vigencia_fim "
            "FROM pcrj_contratos WHERE valor_inicial>1000 AND valor_global>0 "
            "AND valor_global<1e9 AND valor_inicial<1e9").fetchall()
        achados = []
        for r in rows:
            vi, vg, nad = r["vi"], r["vg"], r["num_aditivos"] or 0
            pct = (vg - vi) / vi if vi else 0
            estouro = pct >= 0.25
            serie = nad >= 3
            if not (estouro or serie):
                continue
            # limite aplicável: 50% se o objeto sugere reforma/obra, senão 25%
            obj = _norm_nome(r["objeto"])
            teto = 0.50 if re.search(r"REFORMA|OBRA|EDIFIC|CONSTRU|ENGENHARIA", obj) else 0.25
            cnpj = re.sub(r"\D", "", r["fornecedor_documento"] or "")
            achados.append({
                "contrato": r["cc"], "fornecedor": r["fornecedor_nome"],
                "cnpj": cnpj, "cnpj_fmt": (f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
                                           if len(cnpj) == 14 else cnpj),
                "orgao": r["unidade"] or r["orgao_nome"], "objeto": (r["objeto"] or "")[:160],
                "valor_inicial": vi, "valor_global": vg, "acrescimo": round(vg - vi, 2),
                "pct": round(pct * 100, 1), "num_aditivos": nad, "teto_pct": int(teto * 100),
                "estoura_teto": pct >= teto,
                "acrescimo_real": round(acresc.get(r["cc"], 0), 2) if r["cc"] in acresc else None,
                "tipo": ("estouro" if estouro else "serie"),
                "vigencia_fim": r["vigencia_fim"]})
        # ranking: estoura o teto legal primeiro, depois maior %/mais aditivos
        achados.sort(key=lambda a: (not a["estoura_teto"], -(a["pct"] or 0), -(a["num_aditivos"] or 0)))
        n_estouro = sum(1 for a in achados if a["estoura_teto"])
        n_serie = sum(1 for a in achados if a["tipo"] == "serie")
        return {"ok": True, "achados": achados[:limite], "n": len(achados),
                "n_estoura_teto": n_estouro, "n_serie": n_serie,
                "contratos_analisados": len(rows),
                "explicacao": ("Contrato cujo valor global cresceu acima do limite legal de acréscimo "
                               "(25% em regra; 50% p/ reforma — Lei 14.133 art. 125). Também marca "
                               "CHANGE ORDERS EM SÉRIE (≥3 aditivos), red-flag de fraude por aditivos "
                               "(OCDE/Banco Mundial). 'acréscimo real' vem do termo aditivo quando "
                               "classificado como acréscimo (não reajuste)."),
                "ressalva": ("A variação do valor global inclui REAJUSTE (correção inflacionária), que "
                             "NÃO conta no limite de 25% — confirmar no termo aditivo se é acréscimo "
                             "quantitativo. Base de contratos ainda parcial (PNCP). Indício ≠ acusação.")}
    finally:
        con.close()


def _norm_nome(s: str) -> str:
    """Normaliza nome de pessoa p/ casar sócio×servidor: maiúsculas, sem acento, só letras."""
    import unicodedata
    s = unicodedata.normalize("NFKD", (s or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z ]", " ", s)).strip()


def _frag6(doc: str) -> str:
    """Os 6 dígitos visíveis de um CPF mascarado (senão '')."""
    d = re.sub(r"\D", "", doc or "")
    return d if len(d) == 6 else ""


# favorecido NÃO-comercial: servidor é membro/dirigente pela profissão, não dono-fornecedor
_RX_NAOCOM = re.compile(
    r"MUTUA|\bFUND\b|FUNDAC|INSTITUTO|ASSOCIA|CAIXA DE ASSIST|CAIXA ESCOLAR|COOPERATIVA|SINDICATO|"
    r"CONSELHO|FEDERAC|CONFEDERAC|\bOAB\b|IGREJA|PARTIDO|VIVA RIO|CRUZ VERMELHA|APAE|SANTA CASA|"
    r"OSCIP|\bONG\b|\bAAE\b|\bAEE\b|GREMIO|\bCLUBE\b|CARTORIO|SERVICO NOTARIAL|SOCIEDADE BENEF|"
    r"\bFORUM\b|ESCOLA SUP|CENTRO ACAD|DIRETORIO|CAMARA DOS|ORDEM DOS")
# qualificação de DONO/gerência (servidor-administrador de empresa privada = vedação estatutária)
_RX_DONO = re.compile(r"SOCIO|ADMINISTRADOR|TITULAR|EMPRESARIO|PROPRIET|PRESIDENTE|DIRETOR")
_RX_GERENCIA = re.compile(r"ADMINISTRADOR|PRESIDENTE|DIRETOR|TITULAR|GERENTE")


# Órgão da folha → UG(s) do SIAFE estadual, p/ provar o impedimento do art. 9 (empresa do servidor
# paga pela PRÓPRIA repartição). Só órgãos do Executivo estadual têm UG no OB do SIAFE — TJRJ
# (autônomo) e Câmara Municipal ficam fora (checagem de art. 9 indisponível, mas a vedação de
# gerência permanece). Ampliar conforme novas folhas do Executivo entram.
_ORGAO_FOLHA_UG = {
    "DEFENSORIA": ["110100"],           # DPGE
    "POLICIA MILITAR": ["266500"],      # FUNESPOM/PM
    "POLICIA CIVIL": ["263100"],        # DETRAN e correlatos (aprox.)
    "EDUCACAO": ["190100", "191100"],
    "SAUDE": ["294200"],                # Fundo Estadual de Saúde
}


def _ug_do_orgao_servidor(orgao_nome: str) -> list:
    o = _norm_nome(orgao_nome)
    for chave, ugs in _ORGAO_FOLHA_UG.items():
        if chave in o:
            return ugs
    return []


def socio_servidor(db_path: str | None = None, limite: int = 150) -> dict:
    """Servidor público (folha) que é SÓCIO de empresa fornecedora do Estado — conflito de interesse
    (Lei 14.133 art. 9; interposição art. 337-F CP) e, quando é ADMINISTRADOR, vedação estatutária
    de gerência de empresa privada. Casa por nome + corrobora com fragmento de CPF (mascarado):
    ALTA se os dígitos visíveis coincidem, MÉDIA se só o nome, e DESCARTA quando o CPF conflita
    (homônimo). Exclui entidades de classe. Liga a UG pagadora ao órgão do servidor: se a empresa
    é paga pela PRÓPRIA repartição do servidor, marca impedimento do art. 9 (mesmo_orgao)."""
    import json as _json
    con = _ro(db_path)
    try:
        try:
            _ug_nome = _json.loads((_REPO / "data" / "ug_index_siafe.json").read_text())["ugs"]
        except Exception:
            _ug_nome = {}
        folha: dict[str, list] = {}
        for r in con.execute("SELECT nome, cpf, orgao_nome, cargo, vinculo, fonte "
                             "FROM registros_folha WHERE nome IS NOT NULL"):
            nn = _norm_nome(r["nome"])
            if nn.count(" ") < 1:  # exige nome + sobrenome (reduz homônimo)
                continue
            folha.setdefault(nn, []).append(
                (_frag6(r["cpf"]), r["orgao_nome"], r["cargo"], r["vinculo"], r["fonte"]))
        achados, conflitos = [], 0
        q = ("SELECT s.socio_nome, s.socio_doc, s.cnpj, s.qualificacao, "
             "f.favorecido_nome, f.total_pago, f.n_obs "
             "FROM socios_fornecedor s JOIN favorecido_resumo f ON f.favorecido_cpf=s.cnpj "
             "WHERE f.total_pago>0 AND s.socio_nome<>''")
        for r in con.execute(q):
            emp = r["favorecido_nome"] or ""
            if _RX_NAOCOM.search(_norm_nome(emp)):
                continue
            qual = r["qualificacao"] or ""
            if not _RX_DONO.search(_norm_nome(qual)):
                continue
            nn = _norm_nome(r["socio_nome"])
            cands = folha.get(nn)
            if not cands:
                continue
            fs = _frag6(r["socio_doc"])
            tier, info, houve_conflito = None, None, False
            for (ff, org, cargo, vinc, fonte) in cands:
                if fs and ff:
                    if fs[0:5] == ff[1:6]:   # janelas D4-D9 (sócio) × D3-D8 (folha) → overlap D4-D8
                        tier, info = "ALTA", (org, cargo, vinc, fonte)
                        break
                    houve_conflito = True
                elif not tier:
                    tier, info = "MEDIA", (org, cargo, vinc, fonte)
            if not tier:
                if houve_conflito:
                    conflitos += 1
                continue
            cnpj = r["cnpj"]
            # UGs que pagaram a empresa (nome do índice) + teste de art. 9 (mesma repartição)
            ugs_alvo = set(_ug_do_orgao_servidor(info[0]))
            pagadoras, mesmo_orgao = [], False
            for pr in con.execute("SELECT ug_emitente ug, SUM(valor) v FROM ob_orcamentaria_siafe "
                                  "WHERE credor=? AND valor>0 GROUP BY ug_emitente "
                                  "ORDER BY v DESC LIMIT 3", (cnpj,)):
                pagadoras.append({"ug": pr["ug"], "nome": _ug_nome.get(pr["ug"], ""), "valor": pr["v"]})
                if pr["ug"] in ugs_alvo:
                    mesmo_orgao = True
            achados.append({
                "socio": r["socio_nome"], "cnpj": cnpj,
                "cnpj_fmt": (f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
                             if len(cnpj or "") == 14 else cnpj),
                "empresa": emp, "qualificacao": qual,
                "gerencia": bool(_RX_GERENCIA.search(_norm_nome(qual))),
                "confianca": tier, "servidor_orgao": info[0], "servidor_cargo": info[1],
                "vinculo": info[2], "fonte_folha": info[3],
                "ugs_pagadoras": pagadoras, "mesmo_orgao": mesmo_orgao,
                "art9_verificavel": bool(ugs_alvo),  # False = órgão do servidor não tem UG no SIAFE
                "total_pago": r["total_pago"], "n_obs": r["n_obs"]})
        # ranking: art. 9 (mesmo órgão) primeiro, depois ALTA + gerência + valor
        achados.sort(key=lambda a: (not a["mesmo_orgao"], a["confianca"] != "ALTA",
                                    not a["gerencia"], -(a["total_pago"] or 0)))
        n_alta = sum(1 for a in achados if a["confianca"] == "ALTA")
        n_ger = sum(1 for a in achados if a["gerencia"])
        n_art9 = sum(1 for a in achados if a["mesmo_orgao"])
        return {"ok": True, "achados": achados[:limite], "n": len(achados),
                "n_alta": n_alta, "n_gerencia": n_ger, "n_art9": n_art9,
                "homonimos_descartados": conflitos,
                "folhas": sorted({c[4] for lst in folha.values() for c in lst if c[4]}),
                "explicacao": ("Servidor público (nas folhas coletadas) que é sócio de empresa que "
                               "recebeu do Estado. Servidor ADMINISTRADOR/diretor de empresa privada "
                               "viola a vedação estatutária de gerência; se a empresa contrata com o "
                               "órgão dele, há impedimento (Lei 14.133 art. 9). Confiança ALTA = nome "
                               "e fragmento de CPF batem; MÉDIA = só o nome (homônimo possível)."),
                "ressalva": ("Match por nome + fragmento de CPF mascarado — homônimo com fragmento "
                             "conflitante já é descartado, mas confirmar CPF completo antes de citar. "
                             "Sócio sem gerência (mero quotista) pode ser permitido. Indício ≠ acusação.")}
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
        # quantidade>=2: preço unitário só é comparável em compra REAL por unidade. Linha com
        # quantidade 1 costuma trazer o total do lote/contrato no campo unitário (Água a R$62 mil,
        # serviço a R$85 mi) — poluiria a mediana e viraria falso outlier.
        rows = con.execute(
            "SELECT item_descricao d, unidade_medida un, valor_unitario vu, certame, orgao_nome, "
            "unidade_nome, fornecedor_cnpj, fornecedor_nome, municipio, data_pub "
            "FROM pncp_resultado WHERE ordem_classificacao=1 AND valor_unitario>0 AND quantidade>=2 "
            "AND item_descricao IS NOT NULL AND length(item_descricao)>=3").fetchall()
        grupos: dict[tuple, list] = {}
        for r in rows:
            base = _norm_item(r["d"])
            if not base:
                continue
            # a UNIDADE DE MEDIDA entra na chave: "óleo" em litro ≠ em tambor; "refeição" ≠ "evento".
            un = re.sub(r"[^a-z]", "", (r["un"] or "").lower())[:8]
            grupos.setdefault((base, un), []).append(r)
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
                        "item": r["d"], "unidade_medida": r["un"], "grupo": chave[0],
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


# favorecido que é ENTE PÚBLICO/banco (repasse, não fornecedor comercial) — SQL reutilizável
_SQL_NAO_PUBLICO = (
    "nome_credor NOT LIKE '%FUNDO%' AND nome_credor NOT LIKE '%PREFEITURA%' AND nome_credor NOT LIKE '%MUNICIPIO%' "
    "AND nome_credor NOT LIKE '%MUNICÍPIO%' AND nome_credor NOT LIKE '%SECRETARIA%' AND nome_credor NOT LIKE '%BANCO%' "
    "AND nome_credor NOT LIKE '%CAIXA ECON%' AND nome_credor NOT LIKE '%EQUALIZ%' AND nome_credor NOT LIKE '%TRIBUNAL%' "
    "AND nome_credor NOT LIKE '%ESTADO DO RIO%' AND nome_credor NOT LIKE '%INSTITUTO DE PREV%' "
    "AND nome_credor NOT LIKE '%DEFENSORIA%' AND nome_credor NOT LIKE '%ASSEMBLEIA%'")


def fornecedor_dependente(db_path: str | None = None, min_total: float = 2_000_000,
                          min_share: float = 0.90, limite: int = 120) -> dict:
    """Fornecedor comercial cuja receita do Estado vem ≥90% de UMA ÚNICA unidade gestora — perfil de
    'empresa do órgão' (criada/mantida para atender um comprador só). Exclui repasses a entes públicos."""
    con = _ro(db_path)
    try:
        rows = con.execute(f"""
        WITH tot AS (SELECT credor, SUM(valor) t FROM ob_orcamentaria_siafe
                     WHERE length(credor)=14 AND valor>0 AND {_SQL_NAO_PUBLICO}
                     GROUP BY credor HAVING t >= ?),
        porug AS (SELECT credor, ug_emitente, SUM(valor) v, MAX(nome_credor) nome
                  FROM ob_orcamentaria_siafe WHERE length(credor)=14 AND valor>0
                  GROUP BY credor, ug_emitente)
        SELECT p.credor, p.nome, p.ug_emitente, p.v, t.t,
               (SELECT COUNT(DISTINCT ug_emitente) FROM ob_orcamentaria_siafe
                WHERE credor=p.credor AND valor>0) n_ugs
        FROM porug p JOIN tot t ON t.credor=p.credor
        WHERE p.v >= ? * t.t ORDER BY t.t DESC LIMIT ?""",
                           (min_total, min_share, limite)).fetchall()
        import json as _json
        try:
            ugn = _json.loads((_REPO / "data" / "ug_index_siafe.json").read_text())["ugs"]
        except Exception:
            ugn = {}
        achados = [{
            "cnpj": r["credor"], "nome": r["nome"],
            "cnpj_fmt": (f"{r['credor'][:2]}.{r['credor'][2:5]}.{r['credor'][5:8]}/{r['credor'][8:12]}-{r['credor'][12:]}"),
            "total": r["t"], "valor_ug": r["v"], "share": round(r["v"] / r["t"], 2) if r["t"] else 0,
            "ug": r["ug_emitente"], "ug_nome": ugn.get(r["ug_emitente"], ""), "n_ugs": r["n_ugs"]}
            for r in rows]
        return {"ok": True, "achados": achados, "n": len(achados),
                "explicacao": ("Empresa que recebe quase tudo (≥90%) de uma única unidade gestora do "
                               "Estado. Dependência total de um comprador é o perfil de fornecedor "
                               "cativo/'empresa do órgão' — mercado fechado, risco de direcionamento."),
                "ressalva": ("Monopólio pode ser legítimo (nicho, concessão exclusiva) — cruzar com o "
                             "histórico de licitações do órgão e o QSA. Indício ≠ acusação.")}
    finally:
        con.close()


def corrida_dezembro(db_path: str | None = None, min_total: float = 2_000_000,
                     min_share: float = 0.75, limite: int = 120) -> dict:
    """Fornecedor comercial com ≥75% do valor recebido no ano concentrado em DEZEMBRO — corrida do
    empenho de fim de ano (planejamento deficiente ou direcionamento na virada do exercício)."""
    con = _ro(db_path)
    try:
        rows = con.execute(f"""
        WITH t AS (SELECT credor, MAX(nome_credor) nome, SUM(valor) tot,
                     SUM(CASE WHEN substr(data_emissao,4,2)='12' THEN valor ELSE 0 END) dez,
                     COUNT(*) n_obs
                   FROM ob_orcamentaria_siafe WHERE length(credor)=14 AND valor>0 AND {_SQL_NAO_PUBLICO}
                   GROUP BY credor HAVING tot >= ?)
        SELECT credor, nome, tot, dez, n_obs FROM t WHERE dez >= ? * tot
        ORDER BY tot DESC LIMIT ?""", (min_total, min_share, limite)).fetchall()
        achados = [{
            "cnpj": r["credor"], "nome": r["nome"],
            "cnpj_fmt": (f"{r['credor'][:2]}.{r['credor'][2:5]}.{r['credor'][5:8]}/{r['credor'][8:12]}-{r['credor'][12:]}"),
            "total": r["tot"], "dezembro": r["dez"], "share": round(r["dez"] / r["tot"], 2) if r["tot"] else 0,
            "n_obs": r["n_obs"]} for r in rows]
        return {"ok": True, "achados": achados, "n": len(achados),
                "explicacao": ("Fornecedor que recebeu a maior parte do ano em DEZEMBRO. Concentração "
                               "no fim do exercício é red-flag de 'corrida do empenho' — verba usada às "
                               "pressas antes de perder o orçamento, terreno fértil para dispensa e "
                               "direcionamento."),
                "ressalva": ("Alguns objetos são sazonais (fim de ano) legitimamente — confirmar o "
                             "processo. Indício ≠ acusação.")}
    finally:
        con.close()


def socio_oculto(db_path: str | None = None, min_empresas: int = 3, limite: int = 120) -> dict:
    """Pessoa/holding que é sócia de VÁRIAS (≥3) empresas fornecedoras do Estado — empresário oculto
    ou grupo familiar controlando um leque de fornecedores (indício de fracionamento entre 'concorrentes'
    do mesmo dono). Exclui conselheiros de estatal (não são donos)."""
    con = _ro(db_path)
    try:
        rows = con.execute("""
        SELECT s.socio_nome, s.socio_doc, COUNT(DISTINCT s.cnpj) n_emp, SUM(f.total_pago) tot,
               GROUP_CONCAT(DISTINCT f.favorecido_nome) empresas
        FROM socios_fornecedor s JOIN favorecido_resumo f ON f.favorecido_cpf=s.cnpj
        WHERE s.socio_nome<>'' AND f.total_pago>0
          AND (lower(s.qualificacao) LIKE '%administrador%' OR s.qualificacao LIKE '%Sócio%' OR lower(s.qualificacao) LIKE '%titular%')
          AND s.qualificacao NOT LIKE '%Conselh%'
        GROUP BY s.socio_nome HAVING n_emp >= ? AND tot < 2e9
        ORDER BY n_emp DESC, tot DESC LIMIT ?""", (min_empresas, limite)).fetchall()
        achados = []
        for r in rows:
            emps = [e for e in (r["empresas"] or "").split(",") if e][:8]
            achados.append({
                "socio": r["socio_nome"], "doc": r["socio_doc"], "n_empresas": r["n_emp"],
                "total": r["tot"], "empresas": emps,
                "holding": bool(re.search(r"PARTICIPAC|HOLDING|EMPREEND|LTDA|S\.?A\.?$",
                                          _norm_nome(r["socio_nome"]))) or r["socio_nome"].isupper()})
        return {"ok": True, "achados": achados, "n": len(achados),
                "explicacao": ("Mesma pessoa (ou holding) sócia de várias empresas que vendem ao Estado. "
                               "Um dono por trás de vários fornecedores permite simular concorrência "
                               "entre empresas do mesmo grupo (fracionamento, propostas de cobertura) e "
                               "concentrar contratos disfarçadamente."),
                "ressalva": ("Ser sócio de várias empresas é lícito; o indício é a combinação com "
                             "contratos no mesmo órgão/objeto. Cruzar QSA e certames. Indício ≠ acusação.")}
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
    elif cmd == "aditivos":
        d = aditivos_estouro()
        print(f"aditivos: {d['n']} (estouram teto={d['n_estoura_teto']}, série={d['n_serie']}) "
              f"de {d['contratos_analisados']} contratos")
        for a in d["achados"][:12]:
            print(f"  [{'TETO' if a['estoura_teto'] else a['tipo']}] +{a['pct']:>7.0f}% "
                  f"({a['num_aditivos']}adt) R${a['valor_inicial']:>12,.0f}->R${a['valor_global']:>13,.0f} "
                  f"{(a['fornecedor'] or '')[:20]:20} @ {(a['orgao'] or '')[:22]}")
    elif cmd == "socio_servidor":
        d = socio_servidor()
        print(f"sócio-servidor: {d['n']} (ALTA={d['n_alta']}, gerência={d['n_gerencia']}, "
              f"homônimos descartados={d['homonimos_descartados']})")
        for a in d["achados"][:15]:
            print(f"  [{a['confianca']}] {a['socio'][:24]:24} {a['qualificacao'][:16]:16} de "
                  f"{a['empresa'][:26]:26} R${a['total_pago']:>12,.0f} | {a['servidor_cargo'][:16]:16} "
                  f"@ {(a['servidor_orgao'] or '')[:22]}")
    elif cmd == "sobrepreco":
        d = sobrepreco()
        print(f"itens com preço unitário: {d['itens_com_preco']} | grupos comparáveis: "
              f"{d['grupos_comparaveis']} | achados: {d['n']}")
        for a in d["achados"][:12]:
            print(f"  {a['item'][:34]:34} R${a['preco']:>10,.2f} vs med R${a['mediana']:>9,.2f} "
                  f"({a['razao']}x, n={a['amostra']}) — {(a['orgao'] or '')[:26]}")
