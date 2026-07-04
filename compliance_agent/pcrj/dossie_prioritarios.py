# -*- coding: utf-8 -*-
"""Dossiê dos ALVOS PRIORITÁRIOS (funil OSINT legal) — servidores com maior suspeição.

Capstone do módulo: consolida os sinais públicos já cruzados (acúmulo Câmara∩Prefeitura,
benefício assistencial no Rio, domicílio eleitoral distante, candidatura em outra cidade)
nos servidores de faixa 'forte' e entrega um relatório Kroll acionável para a CPI.

Honesto: são INDÍCIOS por nome (sem CPF completo). O documento diz, para cada alvo, o
próximo passo que PROVA — requisição da CPI (CPF/endereço/ponto) e consulta manual de
tribunal (reclamatória/processos, que têm CAPTCHA e não automatizam). Nunca base vazada.
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from compliance_agent.pcrj import db as _db


def _e(x) -> str:
    return html.escape(str(x or ""))


def montar_ctx(db_path=None, faixa_min: str = "forte") -> dict:
    con = _db.conectar(db_path)
    faixas = ["forte"] if faixa_min == "forte" else ["forte", "verificar"]
    q = ("SELECT nome, gabinetes, cargos_camara, sinais, score, homonimo "
         "FROM pcrj_fantasma_servidor WHERE faixa IN (%s) ORDER BY score DESC, nome"
         % ",".join("?" * len(faixas)))
    rows = con.execute(q, faixas).fetchall()
    con.close()

    linhas = []
    for i, r in enumerate(rows, 1):
        sinais = _e(r["sinais"]).replace(" · ", "<br>• ")
        homon = " <span style='background:#eee;color:#777'>homônimo provável</span>" if r["homonimo"] else ""
        linhas.append(
            f"<tr><td style='text-align:center'>{i}</td>"
            f"<td><b>{_e(r['nome'])}</b>{homon}</td>"
            f"<td>{_e(r['gabinetes'])}</td>"
            f"<td>{_e(r['cargos_camara'])}</td>"
            f"<td style='text-align:center'>{r['score']}</td>"
            f"<td>• {sinais}</td></tr>")
    tabela = ("<table><tr><th>#</th><th>Nome</th><th>Gabinete(s)</th><th>Cargo Câmara</th>"
              "<th>Score</th><th>Indícios convergentes</th></tr>" + "".join(linhas) + "</table>")

    n = len(rows)
    passos = (
        "<p><b>Cada alvo desta lista é INDÍCIO por nome</b> — a prova exige o próximo passo, "
        "que só a CPI tem poder de dar:</p><ol>"
        "<li><b>Requisição à Receita/RH do órgão</b> — CPF completo + endereço atual + vínculos "
        "(confirma se é a mesma pessoa e onde reside).</li>"
        "<li><b>Requisição do registro de ponto/frequência</b> — prova (ou afasta) o funcionário "
        "fantasma: recebe sem comparecer.</li>"
        "<li><b>Consulta de tribunal (TJRJ/TRT1) por nome</b> — reclamatória/processo em outra "
        "comarca (proxy de vínculo em outro lugar). <i>Feita manualmente</i>: a busca por nome tem "
        "CAPTCHA e não se automatiza — mas são só estes " + str(n) + " nomes.</li>"
        "<li><b>Requisição do eSocial/CAGED</b> (via CPI) — vínculo CLT concomitante em outro "
        "empregador.</li></ol>"
        "<p>O acúmulo de <b>dois cargos de professor/saúde</b> é lícito (CF art. 37, XVI) — "
        "confirmar compatibilidade de horário antes de tratar como irregular.</p>")

    return {
        "classificacao": "CONFIDENCIAL — CONTROLE EXTERNO / CPI",
        "titulo": f"Alvos prioritários — {n} servidores com indícios convergentes",
        "subtitulo": "Funil OSINT legal (Câmara×Prefeitura×benefício×eleitoral) — Módulo PCRJ",
        "metodologia": ("Cruzamento nominal de fontes PÚBLICAS (folhas Câmara/Prefeitura, dados "
                        "abertos Bolsa Família/BPC, TSE), desambiguado por fragmento de CPF mascarado. "
                        "Indício, não prova — sem base vazada."),
        "score": n, "faixa": "ALTO",
        "top_flags": [f"{n} alvos 'forte'", "acúmulo+benefício = grau máximo"],
        "secoes": [
            {"titulo": f"1. Lista priorizada ({n})", "html": tabela},
            {"titulo": "2. Próximos passos que PROVAM (poderes da CPI)", "html": passos},
            {"titulo": "3. Método e limitações", "html":
             "<p>Sem CPF nas bases da Câmara → casamento por nome é indício; homônimo (nome em "
             "≥3 municípios ou ≥3 pessoas no benefício) é marcado e não sustenta sozinho. O "
             "benefício assistencial foi desambiguado por fragmento de CPF: dos 415 matches por "
             "nome, só os de <b>1 pessoa única no Rio</b> entraram. Fontes 100% públicas e legais.</p>"}],
        "proveniencia": [{"dado": "Câmara/Prefeitura×BF/BPC×TSE", "estado": "REAL",
                          "fonte": "transparencia.camara / contrachequeapi / portaldatransparencia / TSE",
                          "data": datetime.now().strftime("%d/%m/%Y")}],
        "ressalva": "Indícios por nome para apuração por CPF/ponto via CPI. Não usar base vazada.",
    }


async def gerar(db_path=None) -> dict:
    from compliance_agent.reporting.render_html import html_to_pdf, render_html
    ctx = montar_ctx(db_path)
    h = render_html(ctx)
    base = Path(__file__).resolve().parents[2] / "reports"
    base.mkdir(exist_ok=True)
    pdf = str(base / f"pcrj_alvos_prioritarios_{datetime.now().date()}.pdf")
    await html_to_pdf(h, pdf)
    return {"pdf": pdf, "total": ctx["score"]}


if __name__ == "__main__":
    import asyncio
    print(asyncio.run(gerar()))
