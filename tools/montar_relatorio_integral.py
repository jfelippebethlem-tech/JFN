#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monta o RELATÓRIO FORENSE INTEGRAL (markdown dos agentes + anexos autoritativos do código) → PDF → Yoda."""
import asyncio, re, sys
from datetime import datetime
from pathlib import Path
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from compliance_agent.reporting.render_html import render_html, html_to_pdf
import httpx

ENV = Path("/home/ubuntu/.hermes/.env")
md = Path(REPO / "data/sei_cache/relatorio_integral.md").read_text()
md = md[md.find("# RELATÓRIO FORENSE INTEGRAL"):]   # corta preâmbulo do agente
tab_obs = Path(REPO / "data/sei_cache/tab_obs.html").read_text()
tab_bat = Path(REPO / "data/sei_cache/tab_bateria.html").read_text()


def md2html(block):
    out, tbl = [], []
    def flush():
        if not tbl: return
        rows = [r for r in tbl if not re.match(r"^\s*\|[\s:|-]+\|\s*$", r)]
        if not rows: tbl.clear(); return
        h = "".join(f"<th>{c.strip()}</th>" for c in rows[0].strip().strip("|").split("|"))
        body = "".join("<tr>" + "".join(f"<td>{c.strip()}</td>" for c in r.strip().strip("|").split("|")) + "</tr>" for r in rows[1:])
        out.append(f"<table><tr>{h}</tr>{body}</table>"); tbl.clear()
    for ln in block.splitlines():
        if ln.strip().startswith("|"): tbl.append(ln); continue
        flush()
        s = ln.strip()
        if s.startswith("### "): out.append(f"<h3>{s[4:]}</h3>")
        elif s.startswith("> "): out.append(f"<blockquote>{s[2:]}</blockquote>")
        elif re.match(r"^[-*] ", s): out.append(f"<li>{s[2:]}</li>")
        elif re.match(r"^\d+\.\s", s): out.append(f"<li>{re.sub(r'^\d+\.\s','',s)}</li>")
        elif s: out.append(f"<p>{s}</p>")
    flush()
    h = "\n".join(out)
    h = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", h)
    h = re.sub(r"`(.+?)`", r"<code>\1</code>", h)
    return h


# quebra por seções ## ; injeta anexos
secoes = []
parts = re.split(r"\n##\s+", md)
# parts[0] = título + capa (## 1 começa em parts[1])
cap = parts[0]
secoes.append({"titulo": "Capa e advertência metodológica", "html": md2html(cap.split("# RELATÓRIO FORENSE INTEGRAL", 1)[-1])})
for p in parts[1:]:
    if not p.strip(): continue
    title = p.splitlines()[0].lstrip("# ").strip()
    body = "\n".join(p.splitlines()[1:])
    secoes.append({"titulo": title[:95], "html": md2html(body)})
# anexos autoritativos (números do código)
secoes.append({"titulo": "ANEXO A — Detalhamento completo das 55 OBs por exercício (2021 verificado)", "html": tab_obs})
secoes.append({"titulo": "ANEXO B — Bateria de auditoria T01–T24 (execução determinística)", "html": tab_bat})

ctx = {
    "classificacao": "CONFIDENCIAL — USO INTERNO (controle externo)",
    "titulo": "Relatório Forense Integral — Contrato 005/2021 ITERJ × MGS Clean",
    "subtitulo": "Auditoria independente · SIAFE 1+2 (2021–2026) + árvore SEI OCR + bateria T01-T24 · multi-agente verificado",
    "data": datetime.now().strftime("%d/%m/%Y"), "analista": "JFN — Núcleo de Fiscalização (multi-agente: ler/entender/pensar/auditar)",
    "metodologia": "55 OB SIAFE + 30 docs SEI OCR'd + reconciliação bruto×líquido + bateria T01-T24 + CCT/IN 05-2017/Lei 14.133 · padrão Kroll/Deloitte",
    "score": 60, "faixa": "MÉDIO",
    "top_flags": ["Saldo R$56k do órgão SUPERDIMENSIONADO (erro ×4 + crédito-fantasma bruto×líquido)",
                  "Retroativo Mar-Jun/25 R$35.014,96 em aberto (devido em princípio, teto bruto)",
                  "Duplo-Novembro/2025 R$102.902,89×2 (apurar)", "2021 verificado: 0 OB à MGS",
                  "2026 faturando ~R$7k abaixo do CCT25 (sinal novo)"],
    "secoes": secoes,
    "proveniencia": [
        {"dado": "OBs 2021–2026 (ledger 55 + 2021 verificado-zero)", "estado": "REAL", "fonte": "SIAFE 1 (www5) + SIAFE 2 direto", "data": "19/06/2026"},
        {"dado": "30 docs SEI OCR'd (reconciliação/NL/retenção/empenho)", "estado": "REAL", "fonte": "Árvore SEI itkava (ler() canônico+OCR)", "data": "19/06/2026"},
        {"dado": "CCT da categoria (9,91/6,20/7,5%)", "estado": "REAL", "fonte": "SEAC-RJ/SEEACEC (web)", "data": "19/06/2026"},
    ],
    "ressalva": ("Indício ≠ acusação; INDISPONÍVEL ≠ irregular; presunção de legitimidade; só OB Contabilizado é paga. "
                 "Conformidade plena SUSPENSA até a juntada das NFs e da planilha de custos (processo da contratação). "
                 "Saldo do órgão tem direção de erro confirmada (superdimensionado); crédito real da MGS, se houver, ≤ ~R$35 mil bruto."),
}
nome = f"relatorio_forense_integral_iterj_mgs_{datetime.now().date()}"
destino = str(REPO / "reports" / f"{nome}.pdf")
asyncio.run(html_to_pdf(render_html(ctx), destino))
sz = Path(destino).stat().st_size
print(f"PDF: {destino} {sz} bytes | {len(secoes)} seções")

def key(n):
    m = re.search(rf"^{n}=(.+)$", ENV.read_text(), re.M); return m.group(1).strip().strip('"').strip("'") if m else ""
tok, chat = key("TELEGRAM_BOT_TOKEN"), key("TELEGRAM_CHAT_ID"); base = f"https://api.telegram.org/bot{tok}"
msg = ("📕 *RELATÓRIO FORENSE INTEGRAL — ITERJ × MGS (contrato 005/2021)*\n"
       "_O mais completo: SIAFE 2021–2026 + árvore SEI (30 docs OCR) + bateria T01-T24, multi-agente verificado._\n\n"
       f"*{len(secoes)} seções* · 55 OBs (R$ 5.038.369,24) · 2021 verificado (0 à MGS) · 🟡 atenção.\n\n"
       "*Conclusões principais:*\n"
       "• Saldo R$56k do órgão *superdimensionado* — erro aritmético confirmado (\"4×\"=473.765,88, não 586.950,02) + crédito-fantasma bruto×líquido (R$21k).\n"
       "• Apostilamento = *Δ mensal × 9* (chave-mestra decifrada); retroativos batem ao centavo.\n"
       "• Direção da dívida: *indeterminada* — duplo-Novembro/2025 pode inverter.\n"
       "• Retroativo Mar–Jun/25 (R$35.014,96) *em aberto e devido em princípio* (teto bruto).\n"
       "• 2021: *verificado, 0 OB à MGS* (1º pagamento em jan/2022).\n"
       "• Conformidade *suspensa* até NFs + planilha.\n\n"
       "📎 Relatório integral no PDF (sem limite de páginas).")
print("msg:", httpx.post(f"{base}/sendMessage", data={"chat_id": chat, "text": msg, "parse_mode": "Markdown"}, timeout=30).json().get("ok"))
with open(destino, "rb") as f:
    print("pdf:", httpx.post(f"{base}/sendDocument", data={"chat_id": chat, "caption": "Relatório Forense Integral ITERJ×MGS (PDF)"},
          files={"document": ("relatorio_forense_integral_iterj_mgs.pdf", f, "application/pdf")}, timeout=90).json().get("ok"))
