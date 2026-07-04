# -*- coding: utf-8 -*-
"""DOSSIÊ ÚNICO E COMPLETO — todos os cruzamentos Câmara×Prefeitura×TSE num só documento.

Consolida, com todo o detalhamento (datas dia/mês/ano, exonerado ou não) e honestidade
(sem CPF → indício):
  Parte A  Perícia de vínculos: direção temporal (Pref→Câmara × Câmara→Pref), datas de
           entrada/saída, concomitância, domicílio em outra cidade, comissionados-candidatos.
  Parte B  Linha do tempo ano a ano (nomeações na Câmara e admissões na Prefeitura).
  Parte C  Por parlamentar (titular; suplente em exercício) — nomeados e vínculos.
  Parte D  Gabinetes com alternância + FLAG de continuidade (quem se manteve na transição).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from compliance_agent.pcrj import alternancia, movimentacoes, pericia
from compliance_agent.pcrj import db as _db
from compliance_agent.pcrj import relatorio_gabinete as rg


def _linha_do_tempo(con) -> str:
    """Nomeações na Câmara e admissões na Prefeitura (entre os vinculados), ano a ano."""
    cam = {r["a"]: r["n"] for r in con.execute(
        "SELECT ano_ingresso a, COUNT(DISTINCT nome_norm) n FROM pcrj_camara_servidores "
        "WHERE ano_ingresso IS NOT NULL GROUP BY ano_ingresso")}
    # admissões na Prefeitura (ano) entre os vínculos indício
    adm: dict[int, int] = {}
    exo: dict[int, int] = {}
    for r in con.execute("SELECT observacao FROM pcrj_vinculo_cruzado WHERE confianca='indicio_nome_unico'"):
        m = re.search(r"admissao=\S*/(\d{4})", r["observacao"] or "")
        if m:
            adm[int(m.group(1))] = adm.get(int(m.group(1)), 0) + 1
        me = re.search(r"exoneracao=\S*/(\d{4})", r["observacao"] or "")
        if me:
            exo[int(me.group(1))] = exo.get(int(me.group(1)), 0) + 1
    anos = sorted(set(cam) | set(adm) | set(exo))
    linhas = [f"<tr><td>{a}</td><td style='text-align:right'>{cam.get(a, 0)}</td>"
              f"<td style='text-align:right'>{adm.get(a, 0)}</td>"
              f"<td style='text-align:right'>{exo.get(a, 0)}</td></tr>" for a in anos if a >= 1985]
    return ("<p>Visão ano a ano (o detalhe dia/mês está nas tabelas por pessoa das Partes A/C/D).</p>"
            "<table><tr><th>Ano</th><th>Ingressos na Câmara</th>"
            "<th>Admissões na Prefeitura (vinculados)</th><th>Exonerações na Prefeitura</th></tr>"
            + "".join(linhas) + "</table>")


def montar_ctx(db_path=None) -> dict:
    ctx_p = pericia.montar_ctx(db_path)
    ctx_a = alternancia.montar_ctx(db_path)
    ctx_m = movimentacoes.montar_ctx(db_path)
    con = _db.conectar(db_path)
    try:
        secoes_parlamentar = rg._secoes_por_parlamentar(con)
        timeline = _linha_do_tempo(con)
    finally:
        con.close()

    secoes: list[dict] = []
    secoes.append({"titulo": "PARTE A — Perícia de vínculos (direção, datas, geografia)",
                   "html": "<p>Quem esteve na Prefeitura antes/depois da Câmara, com datas de "
                           "entrada e saída, concomitância e domicílio em outra cidade; e os "
                           "comissionados da Prefeitura (2021+) que já foram candidatos.</p>"})
    secoes += ctx_p["secoes"]
    secoes.append({"titulo": "PARTE B — Linha do tempo (ano a ano)", "html": timeline})
    secoes.append({"titulo": "PARTE C — Nomeados por parlamentar", "html":
                   "<p>Por vereador titular (suplente em exercício explicitado). Ingresso ≥2025 = "
                   "atribuição segura; anterior = legislatura passada (indicativo).</p>"})
    secoes += secoes_parlamentar
    secoes.append({"titulo": "PARTE D — Gabinetes com alternância titular/suplente + continuidade",
                   "html": "<p>Os 5 gabinetes cujos titulares eleitos foram ao Executivo e os "
                           "suplentes assumiram em 02/01/2025. 🚩 CONTINUIDADE = quem se manteve "
                           "no gabinete através da transição (sinal de vínculo persistente).</p>"})
    secoes += ctx_a["secoes"][1:]   # pula o 'Contexto e método' (já resumido acima)
    secoes.append({"titulo": "PARTE E — Movimentações (trajetórias nos dois sentidos, com datas)",
                   "html": "<p>Quem saiu de gabinete de vereador e foi à Prefeitura (com quem/quando), "
                           "Prefeitura→gabinete, candidatos antes/depois da nomeação, e quem passou "
                           "por 2+ gabinetes (suplente↔titular = parlamentares distintos).</p>"})
    secoes += ctx_m["secoes"]

    total = ctx_p["score"]
    return {
        "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO",
        "titulo": "Dossiê completo — vínculos Câmara × Prefeitura × candidaturas (Rio de Janeiro)",
        "subtitulo": f"{total} pessoas com vínculo nas duas casas · todos os cruzamentos — Módulo PCRJ",
        "metodologia": "Cruzamento nominal Câmara×Prefeitura×TSE + análise temporal/geográfica (indício; verificar por CPF)",
        "score": total, "faixa": "ALTO",
        "top_flags": ctx_p["top_flags"],
        "secoes": secoes,
        "proveniencia": ctx_p["proveniencia"],
        "ressalva": "Indícios por nome (sem CPF nas fontes públicas) para apuração no RH. "
                    "Cessão/requisição não é acúmulo. Histórico de gabinete: fonte só publica o "
                    "mapa atual — ingresso anterior a 2025 é de legislatura passada.",
    }


async def gerar(db_path=None) -> dict:
    from compliance_agent.reporting.render_html import html_to_pdf, render_html
    ctx = montar_ctx(db_path)
    html = render_html(ctx)
    base = Path(__file__).resolve().parents[2] / "reports"
    base.mkdir(exist_ok=True)
    pdf = str(base / f"pcrj_dossie_completo_{datetime.now().date()}.pdf")
    await html_to_pdf(html, pdf)
    return {"pdf": pdf, "total": ctx["score"], "secoes": len(ctx["secoes"])}


if __name__ == "__main__":
    import asyncio
    print(asyncio.run(gerar()))
