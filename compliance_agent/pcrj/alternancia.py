# -*- coding: utf-8 -*-
"""Gabinetes com ALTERNÂNCIA titular↔suplente (2025-2028) — atribuição por período.

Fato documentado (câmara.rio, 02/01/2025): no início do mandato, seis titulares eleitos
assumiram cargos no Executivo de Eduardo Paes e os SUPLENTES tomaram posse. Portanto, nos
gabinetes com alternância, o titular ELEITO não chegou a compor o gabinete neste mandato —
o suplente o ocupou desde o início. A análise abaixo separa, por gabinete, os nomeados por
período (data do ato), com honestidade: nomeados a partir de 02/01/2025 estão sob o SUPLENTE;
nomeados de legislatura anterior pertencem a vereador(es) de mandato(s) passado(s).

Sem CPF nas fontes → tudo é indício, não prova.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from compliance_agent.pcrj import db as _db

_POSSE_SUPLENTES = date(2025, 1, 2)   # posse dos suplentes (fonte: câmara.rio, 02/01/2025)
GABINETES_ALTERNANCIA = (6, 11, 20, 41, 44)


def _e(x) -> str:
    import html
    return html.escape(str(x or ""))


def _d(s: str | None) -> date | None:
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", (s or "").strip())
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def _secao_gabinete(con, gab: int) -> dict:
    g = con.execute("SELECT titular, suplente FROM pcrj_gabinetes WHERE gabinete_num=?",
                    (gab,)).fetchone()
    titular = g["titular"] if g else "?"
    suplente = g["suplente"] if g else ""
    servidores = con.execute(
        """SELECT DISTINCT nome, cargo, simbolo, vinculo, data1, ano_ingresso
           FROM pcrj_camara_servidores WHERE gabinete_num=?
           ORDER BY CASE WHEN data1 LIKE '__/__/____'
                    THEN substr(data1,7,4)||substr(data1,4,2)||substr(data1,1,2)
                    ELSE '99999999' END, nome""", (gab,)).fetchall()
    sob_suplente, anteriores = [], []
    for s in servidores:
        dt = _d(s["data1"])
        alvo = sob_suplente if (dt and dt >= _POSSE_SUPLENTES) or (s["ano_ingresso"] or 0) >= 2025 \
            else anteriores
        alvo.append(s)

    def _tab(rows: list) -> str:
        if not rows:
            return "<p class='nota'>—</p>"
        linhas = [f"<tr><td>{_e(r['nome'])}</td><td>{_e(r['cargo'])}</td><td>{_e(r['simbolo'])}</td>"
                  f"<td>{_e(r['vinculo'])}</td><td>{_e(r['data1'])}</td></tr>" for r in rows]
        return ("<table><tr><th>Nome</th><th>Cargo</th><th>Símbolo</th><th>Vínculo</th>"
                "<th>Data do ato</th></tr>" + "".join(linhas) + "</table>")

    html = (
        f"<p><b>Titular eleito:</b> {_e(titular)} (assumiu cargo no Executivo de Paes no início "
        f"do mandato). <b>Suplente em exercício:</b> {_e(suplente)} — ocupa o gabinete desde a "
        f"posse dos suplentes em <b>02/01/2025</b>.</p>"
        f"<p><b>Nomeados sob o suplente {_e(suplente)}</b> (ato ≥ 02/01/2025) — "
        f"{len(sob_suplente)}:</p>" + _tab(sob_suplente)
        + f"<p><span class='flag'>🚩 CONTINUIDADE</span> <b>Mantiveram-se no gabinete através da "
        f"transição</b> (nomeados antes de 02/01/2025 e ainda presentes — sobreviveram à troca "
        f"titular→suplente; sinal de vínculo persistente) — <b>{len(anteriores)}</b>:</p>"
        + _tab(anteriores))
    return {"titulo": f"Gabinete {gab:02d} — {titular} (eleito) / {suplente} (suplente em exercício)",
            "html": html, "_continuidade": len(anteriores)}


def montar_ctx(db_path=None) -> dict:
    con = _db.conectar(db_path)
    try:
        secoes = [
            {"titulo": "Contexto e método", "html":
             "<p>Cinco gabinetes têm <b>alternância</b> titular↔suplente na legislatura 2025-2028. "
             "Em <b>02/01/2025</b> os suplentes tomaram posse porque os titulares eleitos assumiram "
             "cargos no Executivo municipal (fonte: câmara.rio). Logo, neste mandato, quem compôs "
             "cada gabinete foi o <b>suplente</b>, desde o início. Abaixo, por gabinete, os nomeados "
             "sob o suplente (ato ≥ 02/01/2025) e os de período anterior. Sem CPF → indício.</p>"},
        ]
        secoes += [_secao_gabinete(con, g) for g in GABINETES_ALTERNANCIA]
        return {
            "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO",
            "titulo": "Gabinetes com alternância titular↔suplente — nomeados por período",
            "subtitulo": "Gabinetes 06, 11, 20, 41, 44 (legislatura 2025-2028) — Módulo PCRJ",
            "metodologia": "Atribuição por período (data do ato × posse dos suplentes 02/01/2025)",
            "score": len(GABINETES_ALTERNANCIA), "faixa": "MÉDIO",
            "top_flags": ["5 gabinetes", "posse suplentes 02/01/2025"],
            "secoes": secoes,
            "proveniencia": [
                {"dado": "Servidores/gabinetes Câmara", "estado": "REAL",
                 "fonte": "transparencia.camara.rj.gov.br", "data": datetime.now().strftime("%d/%m/%Y")},
                {"dado": "Posse dos suplentes", "estado": "REAL",
                 "fonte": "camara.rio (02/01/2025)", "data": datetime.now().strftime("%d/%m/%Y")}],
            "ressalva": "Indícios por data pública. O período histórico detalhado de cada gabinete "
                        "(mês a mês) exigiria o contracheque por servidor — não incluído nesta v1.",
        }
    finally:
        con.close()


async def gerar(db_path=None) -> dict:
    from compliance_agent.reporting.render_html import html_to_pdf, render_html
    ctx = montar_ctx(db_path)
    html = render_html(ctx)
    base = Path(__file__).resolve().parents[2] / "reports"
    base.mkdir(exist_ok=True)
    pdf = str(base / f"pcrj_alternancia_{datetime.now().date()}.pdf")
    await html_to_pdf(html, pdf)
    return {"pdf": pdf}


if __name__ == "__main__":
    import asyncio
    print(asyncio.run(gerar()))
