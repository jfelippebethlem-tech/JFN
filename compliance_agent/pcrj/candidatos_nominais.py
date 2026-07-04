# -*- coding: utf-8 -*-
"""Lista NOME A NOME de todos (com vínculo Câmara/Prefeitura) que já foram candidatos.

Reúne, por pessoa (sem CPF → indício por nome):
  - candidaturas de servidores da CÂMARA casados no TSE (`tse_candidatura`);
  - candidaturas de COMISSIONADOS da Prefeitura casados no TSE (`pcrj_comissionado_candidato`,
    cruzamento inverso all-RJ).
Cada pessoa: vínculo(s) + todas as candidaturas (ano, cidade, cargo, partido; flags de
outra cidade e antes/depois da nomeação). Ordem alfabética.

OSs (Organizações Sociais): NÃO entram — os RDP da CODESP são agregados, sem nomes de
empregados (ver `os_panorama.py` / memória). Impossível pela fonte pública.
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from compliance_agent.pcrj import db as _db


def _e(x) -> str:
    return html.escape(str(x or ""))


def _coletar(con) -> dict[str, dict]:
    pessoas: dict[str, dict] = {}

    def _get(nn, nome):
        p = pessoas.get(nn)
        if not p:
            p = {"nome": nome, "vinculos": set(), "cands": []}
            pessoas[nn] = p
        return p

    # ingresso na Câmara (p/ flag antes/depois)
    ingresso = {r["nome_norm"]: r["a"] for r in con.execute(
        "SELECT nome_norm, MIN(ano_ingresso) a FROM pcrj_camara_servidores GROUP BY nome_norm")}

    # A) candidatos com vínculo na CÂMARA
    for r in con.execute("SELECT * FROM tse_candidatura ORDER BY nome_tse, ano"):
        nn = r["nome_norm"]
        p = _get(nn, r["nome_tse"])
        gab = con.execute(
            "SELECT GROUP_CONCAT(DISTINCT gabinete_num) g FROM pcrj_camara_servidores "
            "WHERE nome_norm=? AND gabinete_num IS NOT NULL", (nn,)).fetchone()["g"]
        p["vinculos"].add(f"Câmara ({'gab ' + gab if gab else 'admin'})")
        if con.execute("SELECT 1 FROM pcrj_vinculo_cruzado WHERE nome_norm=? "
                       "AND confianca='indicio_nome_unico' LIMIT 1", (nn,)).fetchone():
            p["vinculos"].add("Prefeitura (vínculo)")
        p["cands"].append({"ano": r["ano"], "cidade": r["municipio"], "cargo": r["cargo"],
                           "partido": r["partido"], "outra": r["outra_cidade"],
                           "ref": ingresso.get(nn)})

    # B) candidatos que são COMISSIONADOS da Prefeitura (inverso all-RJ)
    try:
        for r in con.execute("SELECT * FROM pcrj_comissionado_candidato ORDER BY nome_pcrj"):
            nn = r["nome_norm"]
            p = _get(nn, r["nome_pcrj"])
            p["vinculos"].add(f"Prefeitura comissionado ({_e(r['cargo_pcrj'])})")
            if not any(c["ano"] == r["cand_ano"] and c["cidade"] == r["cand_cidade"]
                       for c in p["cands"]):
                p["cands"].append({"ano": r["cand_ano"], "cidade": r["cand_cidade"],
                                   "cargo": r["cand_cargo"], "partido": "",
                                   "outra": 1 if (r["cand_cidade"] or "").upper() != "RIO DE JANEIRO"
                                   else 0, "ref": None})
    except Exception:
        pass
    return pessoas


def _cand_txt(c: dict) -> str:
    q = ""
    if c.get("ref") and c["ano"]:
        q = " · antes da nomeação" if c["ano"] < c["ref"] else (
            " · depois da nomeação" if c["ano"] > c["ref"] else " · no ano da nomeação")
    fora = " [OUTRA CIDADE]" if c["outra"] else ""
    part = f", {c['partido']}" if c.get("partido") else ""
    return f"{_e((c['cargo'] or '').lower())} — {_e((c['cidade'] or '').title())} ({c['ano']}{part}){fora}{q}"


def montar_ctx(db_path=None) -> dict:
    con = _db.conectar(db_path)
    try:
        pessoas = _coletar(con)
    finally:
        con.close()
    linhas = []
    n_fora = 0
    for nn in sorted(pessoas, key=lambda k: pessoas[k]["nome"]):
        p = pessoas[nn]
        cands = sorted(p["cands"], key=lambda c: (c["ano"] or 0))
        if any(c["outra"] for c in cands):
            n_fora += 1
        homon = " <span class='flag' style='background:#eee;color:#777'>homônimo provável</span>" \
            if len({c["cidade"] for c in cands}) >= 3 else ""
        linhas.append(
            f"<tr><td>{_e(p['nome'])}{homon}</td>"
            f"<td>{_e('; '.join(sorted(p['vinculos'])))}</td>"
            f"<td>{'<br>'.join(_cand_txt(c) for c in cands)}</td></tr>")
    tabela = ("<table><tr><th>Nome</th><th>Vínculo(s)</th>"
              "<th>Candidatura(s) — cargo, cidade (ano, partido), antes/depois</th></tr>"
              + "".join(linhas) + "</table>")
    sumario = (f"<table><tr><td><b>Total nome a nome (com vínculo Câmara/Prefeitura)</b></td>"
               f"<td style='text-align:right'><b>{len(pessoas)}</b></td></tr>"
               f"<tr><td>dos quais candidatos em OUTRA cidade</td>"
               f"<td style='text-align:right'>{n_fora}</td></tr></table>")
    return {
        "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO",
        "titulo": "Nome a nome — vinculados à Câmara/Prefeitura que já foram candidatos",
        "subtitulo": "Todas as candidaturas por pessoa (TSE-RJ) — Módulo PCRJ",
        "metodologia": "Cruzamento nominal Câmara/Prefeitura × TSE (indício; verificar por CPF)",
        "score": len(pessoas), "faixa": "ALTO",
        "top_flags": [f"{len(pessoas)} pessoas", f"{n_fora} outra cidade"],
        "secoes": [
            {"titulo": "1. Sumário", "html": sumario},
            {"titulo": f"2. Lista nome a nome ({len(pessoas)})", "html": tabela},
            {"titulo": "3. Método e limitações", "html":
             "<p>Sem CPF → casamento por nome é indício (homônimo em ≥3 cidades sinalizado). "
             "Fontes: servidores da Câmara e comissionados da Prefeitura casados nas candidaturas "
             "do TSE (RJ, 2012-2024). <b>OSs (Organizações Sociais) NÃO entram nominalmente</b>: os "
             "relatórios da CODESP são agregados, sem nomes de empregados — impossível pela fonte "
             "pública. A parte de comissionados da Prefeitura cresce enquanto o cruzamento inverso "
             "all-RJ (51.755 candidatos) roda; a versão final é maior.</p>"}],
        "proveniencia": [{"dado": "Câmara/Prefeitura×TSE", "estado": "REAL",
                          "fonte": "transparencia.camara / contrachequeapi / TSE (RJ)",
                          "data": datetime.now().strftime("%d/%m/%Y")}],
        "ressalva": "Indícios por nome para apuração por CPF. OSs não disponíveis nominalmente.",
    }


async def gerar(db_path=None) -> dict:
    from compliance_agent.reporting.render_html import html_to_pdf, render_html
    ctx = montar_ctx(db_path)
    h = render_html(ctx)
    base = Path(__file__).resolve().parents[2] / "reports"
    base.mkdir(exist_ok=True)
    pdf = str(base / f"pcrj_candidatos_nominais_{datetime.now().date()}.pdf")
    await html_to_pdf(h, pdf)
    return {"pdf": pdf, "total": ctx["score"]}


if __name__ == "__main__":
    import asyncio
    print(asyncio.run(gerar()))
