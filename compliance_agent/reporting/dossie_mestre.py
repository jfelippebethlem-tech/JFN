# -*- coding: utf-8 -*-
"""Dossiê Mestre de licitações — produto PDF (F5.5) que reúne o que o motor sabe sobre um ÓRGÃO ou
sobre o PORTFÓLIO de órgãos, no pipeline Kroll (reporting/render_html).

Não confundir com `tools/dossie_master.py` (dossiê hard-coded do caso Pampolha). Este é o produto
PARAMETRIZADO do dossiê mestre desenhado em docs/superpowers/plans/2026-07-20-dossie-mestre.md:
capa + metodologia transparente + avaliação de conjunto + acatamento de pareceres (quando há
processo) + casos-âncora, tudo determinístico e auditável, com os graus de flag separados.

`montar_ctx_*` são puras/testáveis (sem I/O de PDF); `gerar_pdf_*` chamam o render Kroll.
"""
from __future__ import annotations

from datetime import datetime

from compliance_agent.editais.avaliacao_conjunto import (
    avaliar_orgao,
    avaliar_portfolio,
    avaliar_unidades,
    ctx_secao,
)

_METODOLOGIA = (
    "Índice de Direcionamento de Certame (0-100, 7 famílias: transparência, competição, conluio, "
    "fraude cadastral, preço, execução/aditivos e execução do certame/ata) por convergência "
    "multiplicativa; restritividade de cláusula por teste finalístico (tetos sumulados TCU) × "
    "raridade entre pares; graus de flag A-E (CERTO determinístico / FORTE convergente / SUSPEITO "
    "interpretativo / NÃO-AFERÍVEL / EXCULPADO). Indício ≠ acusação; INDISPONÍVEL ≠ 0."
)


def _secao_metodologia() -> dict:
    return {"titulo": "Metodologia", "html": f"<p>{_METODOLOGIA}</p>"}


def montar_ctx_orgao(orgao_cnpj: str, db_path=None) -> dict:
    """ctx Kroll do dossiê mestre de UM órgão (avaliação de conjunto + metodologia)."""
    av = avaliar_orgao(orgao_cnpj, db_path=db_path)
    nome = av.get("orgao_nome") or orgao_cnpj
    md = av.get("score_mediana")
    faixa = ("EXTREMO" if (md or 0) >= 75 else "ALTO" if (md or 0) >= 50
             else "MEDIO" if (md or 0) >= 25 else "BAIXO")
    top = []
    if av.get("violacoes_saneamento"):
        top.append(f"{av['violacoes_saneamento']} eliminação(ões) trivial(is) sem saneamento")
    for a in av.get("auditoria_tematica") or []:
        top.append(f"auditoria temática: {a['subtipo']} × {a['certames']}")
    return {
        "titulo": "Dossiê Mestre de Licitações — Órgão",
        "subtitulo": f"{nome} (CNPJ {orgao_cnpj})",
        "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO",
        "rotulo_score": "Índice de certame (mediana do órgão)",
        "score": round(md) if md is not None else 0,
        "faixa": faixa,
        "top_flags": top or ["sem flag de conjunto acima do limiar"],
        "metodologia": _METODOLOGIA,
        "data": datetime.now().strftime("%d/%m/%Y"),
        "secoes": [_secao_metodologia(), ctx_secao(av)],
        "_dados": av,
        "ressalva": ("Avaliação de CONJUNTO determinística sobre os certames indexados do órgão. "
                     "Indícios para apuração; presunção de legitimidade. INDISPONÍVEL ≠ 0."),
    }


def _secao_ranking(pf: dict, top_n: int = 25) -> dict:
    linhas = ["<table class='tabela'><tr><th>#</th><th>Órgão</th><th>Certames</th>"
              "<th>Índice mediana</th><th>vs pares</th><th>Gatilhos</th></tr>"]
    for i, o in enumerate(pf["orgaos"][:top_n], 1):
        dv = o.get("desvio_vs_pares")
        dv_s = (f"{dv:+.0f}" if dv is not None else "—")
        gat = []
        if o.get("violacoes_saneamento"):
            gat.append(f"{o['violacoes_saneamento']} elim. trivial")
        if o.get("auditoria_tematica"):
            gat.append("auditoria temática")
        if o.get("hhi_concentrado"):
            gat.append("vitórias concentradas")
        nome = o.get("orgao_nome") or o["orgao_cnpj"]
        md = o.get("score_mediana")
        linhas.append(
            f"<tr><td>{i}</td><td>{nome}</td><td>{o['n_certames_indexados']}</td>"
            f"<td>{md:.1f}</td><td>{dv_s}</td><td>{'; '.join(gat) or '—'}</td></tr>")
    linhas.append("</table>")
    return {"titulo": "Ranking de órgãos por risco de certame", "html": "\n".join(linhas)}


def _secao_unidades(un: dict, top_n: int = 25) -> dict:
    if not un.get("n_unidades"):
        return {"titulo": "Ranking por unidade/secretaria",
                "html": "<p>Sem unidade com certames indexados suficientes — INDISPONÍVEL ≠ 0 "
                        "(a cobertura por unidade cresce com o avanço do PNCP/enxame).</p>"}
    linhas = ["<p>Granularidade por unidade (o CNPJ guarda-chuva do Estado/Município esconde a "
              f"secretaria real). {un['n_unidades']} unidades; mediana dos pares {un['mediana_pares']}.</p>",
              "<table class='tabela'><tr><th>#</th><th>Unidade</th><th>Certames</th>"
              "<th>Índice mediana</th><th>p90</th><th>ALTO/EXTREMO</th><th>vs pares</th></tr>"]
    for i, u in enumerate(un["unidades"][:top_n], 1):
        dv = u.get("desvio_vs_pares")
        dv_s = f"{dv:+.0f}" if dv is not None else "—"
        linhas.append(
            f"<tr><td>{i}</td><td>{u['unidade']}</td><td>{u['n_certames']}</td>"
            f"<td>{u['score_mediana']:.1f}</td><td>{u['score_p90']:.1f}</td>"
            f"<td>{u['n_alto_extremo']}</td><td>{dv_s}</td></tr>")
    linhas.append("</table>")
    return {"titulo": "Ranking por unidade/secretaria", "html": "\n".join(linhas)}


def montar_ctx_portfolio(db_path=None, min_certames: int = 3, top_n: int = 25) -> dict:
    """ctx Kroll do dossiê mestre do PORTFÓLIO (órgãos + unidades/secretarias, peer-benchmark)."""
    pf = avaliar_portfolio(db_path=db_path, min_certames=min_certames)
    un = avaliar_unidades(db_path=db_path, min_certames=min_certames)
    piores = [o for o in pf["orgaos"] if (o.get("desvio_vs_pares") or 0) > 10]
    top = [f"{len(piores)} órgão(s) acima dos pares (+10)"] if piores else []
    aud = [o for o in pf["orgaos"] if o.get("auditoria_tematica")]
    if aud:
        top.append(f"{len(aud)} com gatilho de auditoria temática")
    pior_mediana = max((o.get("score_mediana") or 0) for o in pf["orgaos"]) if pf["orgaos"] else 0
    faixa = ("EXTREMO" if pior_mediana >= 75 else "ALTO" if pior_mediana >= 50
             else "MEDIO" if pior_mediana >= 25 else "BAIXO")
    return {
        "titulo": "Dossiê Mestre de Licitações — Portfólio de Órgãos",
        "subtitulo": f"{pf['n_orgaos']} órgãos com ≥{min_certames} certames indexados "
                     f"(mediana dos pares: {pf['mediana_pares']})",
        "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO",
        "rotulo_score": "Pior mediana de órgão no portfólio",
        "score": round(pior_mediana),
        "faixa": faixa,
        "top_flags": top or ["portfólio sem outlier acima do limiar"],
        "metodologia": _METODOLOGIA,
        "data": datetime.now().strftime("%d/%m/%Y"),
        "secoes": [_secao_metodologia(), _secao_ranking(pf, top_n), _secao_unidades(un, top_n)],
        "_dados": {"n_orgaos": pf["n_orgaos"], "mediana_pares": pf["mediana_pares"],
                   "n_unidades": un["n_unidades"]},
        "ressalva": ("Peer-benchmark determinístico entre órgãos (desvio da mediana do órgão vs mediana "
                     "dos pares). Indícios para priorização de auditoria; presunção de legitimidade."),
    }


async def gerar_pdf_orgao(orgao_cnpj: str, db_path=None) -> dict:
    from compliance_agent.reporting.render_html import gerar_pdf
    ctx = montar_ctx_orgao(orgao_cnpj, db_path=db_path)
    path = await gerar_pdf(ctx, f"dossie_mestre_orgao_{orgao_cnpj}")
    return {"ok": True, "path_pdf": path, "titulo": ctx["subtitulo"], "ctx": ctx}


async def gerar_pdf_portfolio(db_path=None, min_certames: int = 3) -> dict:
    from compliance_agent.reporting.render_html import gerar_pdf
    ctx = montar_ctx_portfolio(db_path=db_path, min_certames=min_certames)
    path = await gerar_pdf(ctx, "dossie_mestre_portfolio")
    return {"ok": True, "path_pdf": path, "titulo": ctx["subtitulo"], "ctx": ctx}
