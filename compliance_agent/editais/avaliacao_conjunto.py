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
        rows = _q(con, "SELECT ci.certame, ci.score, ci.faixa, ci.prioridade, ci.confianca "
                       "FROM certame_indice ci "
                       "JOIN edital_documento ed ON ed.numero_controle_pncp = ci.certame "
                       "WHERE ed.orgao_cnpj = ? AND ci.score IS NOT NULL", (orgao_cnpj,))
        # confianca=0 → NENHUMA das 7 famílias era analisável: é INDISPONÍVEL, não "score 0".
        # Entrar na mediana afundaria o órgão inteiro para 0 e mascararia o padrão real.
        avaliados = [r for r in rows if (r["confianca"] or 0) > 0]
        scores = sorted(r["score"] for r in avaliados)
        n = len(rows)

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

        casos_ancora = sorted(avaliados or rows, key=lambda r: -(r["prioridade"] or 0))[:5]
        nome_r = _q(con, "SELECT orgao_nome FROM pncp_resultado WHERE orgao_cnpj=? "
                         "AND orgao_nome IS NOT NULL LIMIT 1", (orgao_cnpj,))
        return {
            "orgao_cnpj": orgao_cnpj,
            "orgao_nome": (nome_r[0]["orgao_nome"] if nome_r else None),
            "n_certames_indexados": n,
            "n_avaliados": len(avaliados),
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
            "_nota": "conjunto determinístico e auditável; mediana/p90 só sobre certames com confiança>0 "
                     "(≥1 família analisável) — indexado sem família analisável = INDISPONÍVEL (≠ 0)",
        }
    finally:
        con.close()


def avaliar_portfolio(db_path=None, min_certames: int = 3,
                      esferas: tuple[str, ...] | None = ("estadual-rj", "municipal-rio")) -> dict:
    """Portfólio: todos os órgãos com ≥ min_certames indexados, ranqueados + peer-benchmark
    (mediana do órgão vs mediana dos PARES — peer_diff um nível acima).

    `esferas` restringe à JURISDIÇÃO fiscalizada (default estadual-RJ + municipal-Rio = TCE-RJ/TCM-RJ;
    o dono é Deputado Estadual do RJ). Sem o filtro o ranking enche de órgão FEDERAL que apenas licita
    no RJ (uf='RJ' é local de compra, não esfera) — fora da jurisdição. None = sem filtro. A esfera vem
    de pcrj/esfera.classificar_esfera (CNPJ-raiz guarda-chuva + nome), não de UF."""
    from compliance_agent.pcrj.esfera import classificar_esfera

    con = _ro(db_path)
    try:
        # o GROUP BY é só sobre certame_indice×edital_documento (barato); o nome vem de subquery
        # escalar (LEFT JOIN em pncp_resultado, milhares de linhas por CNPJ guarda-chuva, explodia)
        rows = _q(con, "SELECT ed.orgao_cnpj, COUNT(DISTINCT ci.certame) AS n, "
                       "(SELECT pr.orgao_nome FROM pncp_resultado pr WHERE pr.orgao_cnpj = ed.orgao_cnpj "
                       " AND pr.orgao_nome IS NOT NULL LIMIT 1) AS nome "
                       "FROM certame_indice ci JOIN edital_documento ed "
                       "ON ed.numero_controle_pncp = ci.certame "
                       "WHERE ed.orgao_cnpj IS NOT NULL GROUP BY ed.orgao_cnpj HAVING n >= ?",
                       (min_certames,))
    finally:
        con.close()
    orgaos = []
    for r in rows:
        if esferas and classificar_esfera(r["nome"] or "", r["orgao_cnpj"]) not in esferas:
            continue
        orgaos.append(r["orgao_cnpj"])
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


def avaliar_unidades(raizes_cnpj: tuple[str, ...] = ("42498600", "42498733"),
                     db_path=None, min_certames: int = 3) -> dict:
    """Ranking por UNIDADE/secretaria (granularidade que orgao_cnpj esconde: todo órgão estadual
    compartilha o CNPJ guarda-chuva 42498600). Agrupa os certames indexados por
    `pncp_resultado.unidade_nome` — Hospital Pedro Ernesto, Fundo Estadual de Saúde, etc.

    Cobertura HONESTA: só rankeia certames que TÊM unidade em pncp_resultado (o índice cobre mais
    editais do que o PNCP expõe vencedor); as unidades crescem conforme o PNCP/enxame avançam."""
    con = _ro(db_path)
    try:
        marks = ",".join("?" for _ in raizes_cnpj)
        rows = _q(con,
                  "SELECT pr.unidade_nome AS unidade, ci.score, ci.faixa, ci.prioridade, ci.certame, ci.confianca "
                  "FROM certame_indice ci JOIN edital_documento ed "
                  "ON ed.numero_controle_pncp = ci.certame "
                  "JOIN pncp_resultado pr ON pr.certame = ci.certame "
                  "WHERE substr(ed.orgao_cnpj,1,8) IN (" + marks + ") "
                  "AND pr.unidade_nome IS NOT NULL AND ci.score IS NOT NULL",
                  tuple(raizes_cnpj))
    finally:
        con.close()
    por_unidade: dict[str, list] = {}
    for r in rows:
        por_unidade.setdefault(r["unidade"], []).append(r)
    unidades = []
    for nome, rs in por_unidade.items():
        certames = {r["certame"]: r for r in rs}.values()  # dedup por certame
        if len(certames) < min_certames:
            continue
        # mesma doutrina do avaliar_orgao: confianca=0 = INDISPONÍVEL, fora da mediana
        avaliados = [r for r in certames if (r["confianca"] or 0) > 0]
        scores = sorted(r["score"] for r in avaliados)
        ancora = sorted(avaliados or certames, key=lambda r: -(r["prioridade"] or 0))[:3]
        unidades.append({
            "unidade": nome,
            "n_certames": len(certames),
            "n_avaliados": len(avaliados),
            "score_mediana": _quantil(scores, 0.5),
            "score_p90": _quantil(scores, 0.9),
            "n_alto_extremo": sum(1 for r in certames if r["faixa"] in ("ALTO", "EXTREMO")),
            "casos_ancora": [{"certame": r["certame"], "score": r["score"], "faixa": r["faixa"]}
                             for r in ancora],
        })
    medianas = sorted(u["score_mediana"] for u in unidades if u["score_mediana"] is not None)
    mediana_pares = _quantil(medianas, 0.5)
    for u in unidades:
        u["desvio_vs_pares"] = (round(u["score_mediana"] - mediana_pares, 2)
                                if u["score_mediana"] is not None and mediana_pares is not None else None)
    unidades.sort(key=lambda u: -(u["score_mediana"] or 0))
    return {"n_unidades": len(unidades), "mediana_pares": mediana_pares, "unidades": unidades,
            "_nota": "granularidade por unidade (pncp_resultado.unidade_nome); só certames com unidade "
                     "conhecida entram — cobertura cresce com PNCP/enxame (INDISPONÍVEL ≠ 0)"}


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
