#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Relatório FINAL ITERJ→MGS (padrão casa) com veredito documentado (SEI primário + reconciliação derivada).
Gera PDF e envia ao Yoda."""
import asyncio, json, re, sqlite3, sys
from collections import Counter
from datetime import datetime
from pathlib import Path
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from compliance_agent.reporting.render_html import render_html, html_to_pdf
import httpx

DB = REPO / "data/compliance.db"; CNPJ = "19088605000104"; UG = "133100"
ENV = Path("/home/ubuntu/.hermes/.env")
con = sqlite3.connect(DB); cur = con.cursor()
brl = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
def tab(h, rows):
    return "<table><tr>" + "".join(f"<th>{x}</th>" for x in h) + "</tr>" + "".join("<tr>"+"".join(f"<td>{c}</td>" for c in r)+"</tr>" for r in rows) + "</table>"

rows = cur.execute("""SELECT exercicio,COUNT(*),SUM(valor) FROM ob_orcamentaria_siafe
  WHERE ug_emitente=? AND credor=? GROUP BY exercicio ORDER BY exercicio""", (UG, CNPJ)).fetchall()
N = sum(r[1] for r in rows); TOTAL = sum(r[2] for r in rows)
SIS = lambda y: "SIAFE 1 (www5)" if y <= 2023 else "SIAFE 2"

secoes = []
secoes.append({"titulo": "1. Sumário executivo e veredito", "html":
    f"<p><b>Objeto.</b> Pagamentos do <b>ITERJ</b> (UG 133100) à <b>MGS Clean</b> (CNPJ 19.088.605/0001-04), "
    f"contrato <b>005/2021</b> (limpeza/conservação), competências <b>Dez/2021–Mar/2026</b>: "
    f"<b>{N} OBs</b>, <b>R$ {brl(TOTAL)}</b> (liquidação; empenho ≠ OB).</p>"
    f"<p><b>Gatilho.</b> Meses com 2 OBs e um aparente “+1 mês” em 2023 levantaram a hipótese de pagamento em duplicidade.</p>"
    f"<p><b>Veredito.</b> <b>Duplicidade NÃO evidenciada.</b> Os descasamentos de competência são explicados, "
    f"com base documental, por: <b>retroativos de repactuação</b> (CCT/dissídio, mar–jun); <b>ciclo de renovação "
    f"Nov-a-Nov</b> (não ano civil); <b>glosas</b> (Nov/25–Fev/26); <b>splits de desembolso</b> (mesmo empenho) e "
    f"<b>lag de pagamento</b> (nunca antecipado). Fonte primária (SIAFE + Despacho de Liquidação): <b>1 NL por "
    f"competência</b>, e as OBs gêmeas de 10/2025 têm <b>NLs distintas</b>. Nenhuma OB estornada. "
    f"A própria contabilidade do ITERJ reconciliou o contrato e apurou <b>crédito de R$ 56.044,28 a favor da MGS</b>, "
    f"encaminhando à <b>Auditoria Interna (AUDIN)</b>. Presunção de legitimidade; indício ≠ acusação.</p>"})

secoes.append({"titulo": "2. Pagamentos por exercício (SIAFE direto — fonte primária)", "html":
    tab(["Exercício", "Sistema", "OBs", "Valor pago (R$)"],
        [[ex, SIS(ex), n, "R$ "+brl(s)] for ex, n, s in rows] + [["<b>Total</b>", "", f"<b>{N}</b>", f"<b>R$ {brl(TOTAL)}</b>"]])})

secoes.append({"titulo": "3. Verificação de duplicidade — primário vs. derivado", "html":
    tab(["Causa do descasamento", "Evidência", "Tipo"],
        [["Retroativo de repactuação (CCT, mar–jun)", "Relatório ASSCONT; valores conferem", "derivada (forte)"],
         ["Renovação Nov-a-Nov (não jan–dez)", "Contrato 005/2021 (renov. 20/21 nov)", "<b>primária</b>"],
         ["Glosas Nov/25–Fev/26 (R$118.441,47→R$113.184,14)", "Relatório ASSCONT", "derivada"],
         ["1 NL por competência; gêmeas 10/2025 com NLs distintas (472≠493)", "Despacho de Liquidação + SIAFE", "<b>primária</b>"],
         ["Nenhuma OB estornada; lag nunca negativo", "ob_orcamentaria_siafe (status/datas)", "<b>primária</b>"]])
    + "<p class='nota'><b>Ressalva:</b> a imagem escaneada da NF mensal não foi OCR'd (anexos SEI deram ERR_ABORTED no "
      "acesso direto — limitação de tooling do visualizador, não de evidência). A confirmação se apoia nas NLs "
      "distintas e na reconciliação institucional.</p>"})

secoes.append({"titulo": "4. Reconciliação institucional (ASSCONT/ITERJ → AUDIN)", "html":
    "<p>A Assessoria Contábil do ITERJ produziu um <b>Relatório de Créditos e Débitos</b> do contrato 005/2021 "
    "(2021 → glosa de Fev/2026). Evolução do custo mensal por CCT: R$ 90.419,34 → 98.276,62 → 103.988,53 → "
    "109.687,73 → <b>R$ 118.441,47</b>. Apurou <b>crédito de R$ 56.044,28 a favor da MGS</b> (retroativo da "
    "repactuação 2025 + diferença das NFs glosadas). A DIRAF encaminhou os pagamentos à <b>Auditoria Interna "
    "(AUDIN)</b>. <b>Documento DERIVADO</b> (a contabilidade do próprio órgão) — ponderado, não tratado como prova "
    "final; relevante por ser admissão institucional de glosas e de saldo credor ao fornecedor.</p>"})

ctx = {
    "classificacao": "CONFIDENCIAL — USO INTERNO (controle externo)",
    "titulo": "Relatório de Inteligência — ITERJ × MGS Clean (verificação de duplicidade)",
    "subtitulo": "Contrato 005/2021 · OBs 2021–2026 · SIAFE direto + árvore SEI (itkava) · veredito documentado",
    "data": datetime.now().strftime("%d/%m/%Y"),
    "analista": "JFN — Núcleo de Fiscalização (automatizado)",
    "metodologia": "OB=liquidação · competência/NL/RE/PD · fonte primária (SIAFE+SEI) ponderada vs. derivada · padrão Kroll/Deloitte",
    "score": 18, "faixa": "BAIXO",
    "top_flags": ["Duplicidade NÃO evidenciada (NLs distintas por competência)",
                  "Reconciliação do órgão: crédito R$ 56.044,28 à MGS",
                  "Pagamentos sob análise da Auditoria Interna (AUDIN)",
                  "Resíduo: imagem da NF não OCR'd (gargalo de tooling)"],
    "secoes": secoes,
    "proveniencia": [
        {"dado": "OBs/NL/RE/PD ITERJ→MGS", "estado": "REAL", "fonte": "SIAFE-Rio direto (raspagem itkava/CDP)", "data": "19/06/2026"},
        {"dado": "NL por competência; reconciliação; glosas", "estado": "REAL", "fonte": "Árvore SEI 330005/* (itkava)", "data": "19/06/2026"},
    ],
    "ressalva": ("Duplicidade não evidenciada, com forte base documental. Documento de reconciliação é derivado "
                 "(órgão interessado), ponderado. Imagem da NF mensal não OCR'd (limitação de extração). Indício ≠ acusação."),
}
nome = f"relatorio_iterj_mgs_final_{datetime.now().date()}"
destino = str(REPO / "reports" / f"{nome}.pdf")
asyncio.run(html_to_pdf(render_html(ctx), destino))
print("PDF:", destino, Path(destino).stat().st_size, "bytes")

def key(n):
    m = re.search(rf"^{n}=(.+)$", ENV.read_text(), re.M); return m.group(1).strip().strip('"').strip("'") if m else ""
tok, chat = key("TELEGRAM_BOT_TOKEN"), key("TELEGRAM_CHAT_ID"); base = f"https://api.telegram.org/bot{tok}"
msg = ("📑 *ITERJ × MGS Clean — Relatório FINAL (duplicidade)* — PDF\n"
       "Contrato 005/2021 · SIAFE direto + árvore SEI (itkava)\n\n"
       "• Veredito: *duplicidade NÃO evidenciada* (documentado)\n"
       "• Descasamentos = retroativo de repactuação + ciclo Nov-Nov + glosas + splits\n"
       "• *Primária:* 1 NL por competência; gêmeas 10/2025 com NLs distintas\n"
       "• Reconciliação do ITERJ: *crédito R$ 56.044,28 à MGS*; sob *AUDIN*\n"
       "• Ressalva honesta: imagem da NF não OCR'd (gargalo de tooling)\n"
       "• Rating 🟢 BAIXO · indício ≠ acusação")
print("msg:", httpx.post(f"{base}/sendMessage", data={"chat_id": chat, "text": msg, "parse_mode": "Markdown"}, timeout=30).json().get("ok"))
with open(destino, "rb") as f:
    print("pdf:", httpx.post(f"{base}/sendDocument", data={"chat_id": chat, "caption": "ITERJ×MGS — Relatório final (duplicidade afastada, documentado)"},
          files={"document": ("relatorio_iterj_mgs_final.pdf", f, "application/pdf")}, timeout=60).json().get("ok"))
con.close()
