# -*- coding: utf-8 -*-
"""Avaliação de CONJUNTO — os certames de um órgão (e o portfólio de órgãos) analisados como um todo.

O salto de nível do dossiê mestre (plano 2026-07-20 §5): um processo isolado mostra um vício; o
CONJUNTO mostra o padrão — distribuição do índice de certame, reincidência do mesmo tipo de cláusula
restritiva, inabilitação trivial recorrente, concentração de vencedores (HHI) e o desvio do órgão
frente aos pares (peer-benchmark, mesma doutrina do peer_diff um nível acima).

Leitura pura (mode=ro), sobre o que JÁ está persistido: `certame_indice`, `edital_documento`,
`clausula_veredito`, `certame_julgamento`, `pncp_resultado`. Sem dado → INDISPONÍVEL (≠ 0).
Interpretação subjetiva do padrão NÃO mora aqui (vai à rubrica LLM de produto, com este dict de
insumo) — aqui é só o determinístico auditável.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from compliance_agent.emendas.db import _DB_PADRAO
from compliance_agent.lex_base_empirica import _quantil

REINCIDENCIA_AUDITORIA = 3          # mesmo subtipo restritivo em ≥3 certames → auditoria temática
HHI_CONCENTRADO = 0.25              # HHI de vitórias acima disso = mercado concentrado (referência antitruste)
SCORE_RESTRITIVA = 7                # cláusula com score_final ≥ 7/10 conta como restritiva


def _ro(db_path=None) -> sqlite3.Connection:
    p = Path(db_path) if db_path else _DB_PADRAO
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _q(con, sql, params=()) -> list:
    try:
        return list(con.execute(sql, params))
    except sqlite3.OperationalError:
        return []  # tabela ausente nesta base → INDISPONÍVEL, nunca inventa


def avaliar_orgao(orgao_cnpj: str, db_path=None) -> dict:
    """Avaliação de conjunto de UM órgão (CNPJ do órgão em edital_documento)."""
    con = _ro(db_path)
    try:
        rows = _q(con, "SELECT ci.certame, ci.score, ci.faixa, ci.prioridade FROM certame_indice ci "
                       "JOIN edital_documento ed ON ed.numero_controle_pncp = ci.certame "
                       "WHERE ed.orgao_cnpj = ? AND ci.score IS NOT NULL", (orgao_cnpj,))
        scores = sorted(r["score"] for r in rows)
        n = len(scores)

        # reincidência por subtipo de cláusula restritiva (a assinatura do modus operandi)
        rein = _q(con, "SELECT ec.subtipo, COUNT(DISTINCT cv.numero_controle_pncp) AS certames "
                       "FROM clausula_veredito cv "
                       "JOIN edital_clausula ec ON ec.id = cv.clausula_id "
                       "JOIN edital_documento ed ON ed.numero_controle_pncp = cv.numero_controle_pncp "
                       "WHERE ed.orgao_cnpj = ? AND cv.score_final >= ? AND ec.subtipo IS NOT NULL "
                       "GROUP BY ec.subtipo ORDER BY certames DESC", (orgao_cnpj, SCORE_RESTRITIVA))
        reincidentes = [{"subtipo": r["subtipo"], "certames": r["certames"]} for r in rein]
        auditoria = [r for r in reincidentes if r["certames"] >= REINCIDENCIA_AUDITORIA]

        # o que ocorreu nas sessões (quando persistido): trivialidade agregada
        julg = _q(con, "SELECT cj.trivialidade_json FROM certame_julgamento cj "
                       "JOIN edital_documento ed ON ed.numero_controle_pncp = cj.certame "
                       "WHERE ed.orgao_cnpj = ?", (orgao_cnpj,))
        viol_sane = triviais = com_ata = 0
        for r in julg:
            t = json.loads(r["trivialidade_json"] or "{}")
            com_ata += 1
            viol_sane += t.get("violacoes_saneamento") or 0
            triviais += t.get("triviais") or 0

        # concentração de vitórias (HHI por nº de certames vencidos)
        venc = _q(con, "SELECT pr.fornecedor_cnpj, COUNT(DISTINCT pr.certame) AS vitorias "
                       "FROM pncp_resultado pr JOIN edital_documento ed "
                       "ON ed.numero_controle_pncp = pr.certame "
                       "WHERE ed.orgao_cnpj = ? AND (pr.ordem_classificacao = 1 OR "
                       "pr.ordem_classificacao IS NULL) AND pr.fornecedor_cnpj IS NOT NULL "
                       "GROUP BY pr.fornecedor_cnpj", (orgao_cnpj,))
        tot_v = sum(r["vitorias"] for r in venc)
        hhi = round(sum((r["vitorias"] / tot_v) ** 2 for r in venc), 4) if tot_v else None

        casos_ancora = sorted(rows, key=lambda r: -(r["prioridade"] or 0))[:5]
        return {
            "orgao_cnpj": orgao_cnpj,
            "n_certames_indexados": n,
            "score_mediana": _quantil(scores, 0.5),
            "score_p90": _quantil(scores, 0.9),
            "n_alto_extremo": sum(1 for r in rows if r["faixa"] in ("ALTO", "EXTREMO")),
            "reincidencia_subtipos": reincidentes,
            "auditoria_tematica": [{"subtipo": a["subtipo"], "certames": a["certames"],
                                    "fundamento": f"mesmo padrão restritivo em {a['certames']} certames "
                                                  "do órgão — auditoria temática, não representação avulsa"}
                                   for a in auditoria],
            "sessoes_com_ata": com_ata,
            "inabilitacoes_triviais": triviais,
            "violacoes_saneamento": viol_sane,
            "hhi_vitorias": hhi,
            "hhi_concentrado": (hhi is not None and hhi >= HHI_CONCENTRADO) or None,
            "casos_ancora": [{"certame": r["certame"], "score": r["score"], "faixa": r["faixa"]}
                             for r in casos_ancora],
            "_nota": "conjunto determinístico e auditável; sem certame indexado → tudo INDISPONÍVEL (≠ 0)",
        }
    finally:
        con.close()


def avaliar_portfolio(db_path=None, min_certames: int = 3) -> dict:
    """Portfólio: todos os órgãos com ≥ min_certames indexados, ranqueados + peer-benchmark
    (mediana do órgão vs mediana dos PARES — peer_diff um nível acima)."""
    con = _ro(db_path)
    try:
        orgaos = [r["orgao_cnpj"] for r in
                  _q(con, "SELECT ed.orgao_cnpj, COUNT(DISTINCT ci.certame) AS n FROM certame_indice ci "
                          "JOIN edital_documento ed ON ed.numero_controle_pncp = ci.certame "
                          "WHERE ed.orgao_cnpj IS NOT NULL GROUP BY ed.orgao_cnpj "
                          "HAVING n >= ?", (min_certames,))]
    finally:
        con.close()
    avaliacoes = [avaliar_orgao(o, db_path) for o in orgaos]
    medianas = sorted(a["score_mediana"] for a in avaliacoes if a["score_mediana"] is not None)
    mediana_pares = _quantil(medianas, 0.5)
    for a in avaliacoes:
        a["desvio_vs_pares"] = (round(a["score_mediana"] - mediana_pares, 2)
                                if a["score_mediana"] is not None and mediana_pares is not None else None)
    avaliacoes.sort(key=lambda a: -(a["score_mediana"] or 0))
    return {"n_orgaos": len(avaliacoes), "mediana_pares": mediana_pares, "orgaos": avaliacoes,
            "_nota": f"órgãos com ≥{min_certames} certames indexados; desvio_vs_pares = mediana do órgão "
                     "− mediana dos pares (positivo = pior que os pares)"}


def ctx_secao(av: dict) -> dict:
    """Converte a avaliação de um órgão no contrato de seção do dossiê ({titulo, html}) — pluga em
    `_ctx_dossie`/consolidado sem tocar no render (pipeline Kroll)."""
    if not av.get("n_certames_indexados"):
        html = "<p>Sem certames indexados para este órgão — avaliação de conjunto INDISPONÍVEL (≠ 0).</p>"
        return {"titulo": "Avaliação de conjunto (portfólio de certames)", "html": html}
    linhas = [
        "<table class='tabela'><tr><th>Métrica</th><th>Valor</th></tr>",
        f"<tr><td>Certames indexados</td><td>{av['n_certames_indexados']}</td></tr>",
        f"<tr><td>Índice de certame — mediana</td><td>{av['score_mediana']:.1f}</td></tr>",
        f"<tr><td>Índice de certame — p90</td><td>{av['score_p90']:.1f}</td></tr>",
        f"<tr><td>Certames ALTO/EXTREMO</td><td>{av['n_alto_extremo']}</td></tr>",
        f"<tr><td>Sessões com ata persistida</td><td>{av['sessoes_com_ata']}</td></tr>",
        f"<tr><td>Eliminações por motivo trivial sem saneamento</td><td>{av['violacoes_saneamento']}</td></tr>",
        f"<tr><td>HHI de vitórias</td><td>{av['hhi_vitorias'] if av['hhi_vitorias'] is not None else 'INDISPONÍVEL'}</td></tr>",
        "</table>"]
    if av.get("auditoria_tematica"):
        linhas.append("<blockquote><b>Gatilho de auditoria temática:</b> " + "; ".join(
            f"{a['subtipo']} em {a['certames']} certames" for a in av["auditoria_tematica"]) + ".</blockquote>")
    if av.get("casos_ancora"):
        linhas.append("<p><b>Casos-âncora:</b> " + "; ".join(
            f"{c['certame']} ({c['score']:.0f}/{c['faixa']})" for c in av["casos_ancora"]) + "</p>")
    return {"titulo": "Avaliação de conjunto (portfólio de certames)", "html": "\n".join(linhas)}
