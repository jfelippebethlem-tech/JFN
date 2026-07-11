#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Renderiza a síntese forense (markdown) em PDF padrão casa e envia ao Yoda com resumo das 4 respostas."""
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from compliance_agent.reporting.render_html import render_html, html_to_pdf
import httpx

ENV = Path("/home/ubuntu/.hermes/.env")
md = Path(REPO / "data/sei_cache/forense_sintese.md").read_text()
md = md.split("# VEREDITO FORENSE", 1)[-1]  # corta o preâmbulo do agente
md = "# VEREDITO FORENSE" + md


def md2html(block):
    """Conversor markdown→HTML minimalista (tabelas, bold, listas, blockquote)."""
    out, tbl = [], []
    def flush_tbl():
        if not tbl: return
        rows = [r for r in tbl if not re.match(r"^\s*\|[\s:|-]+\|\s*$", r)]
        h = "".join(f"<th>{c.strip()}</th>" for c in rows[0].strip().strip("|").split("|"))
        body = ""
        for r in rows[1:]:
            body += "<tr>" + "".join(f"<td>{c.strip()}</td>" for c in r.strip().strip("|").split("|")) + "</tr>"
        out.append(f"<table><tr>{h}</tr>{body}</table>"); tbl.clear()
    for ln in block.splitlines():
        if ln.strip().startswith("|"):
            tbl.append(ln); continue
        flush_tbl()
        if ln.startswith("> "):
            out.append(f"<blockquote>{ln[2:]}</blockquote>")
        elif ln.startswith("- "):
            out.append(f"<li>{ln[2:]}</li>")
        elif ln.strip():
            out.append(f"<p>{ln}</p>")
    flush_tbl()
    h = "\n".join(out)
    h = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", h)
    h = re.sub(r"`(.+?)`", r"<code>\1</code>", h)
    return h


secoes = []
for part in re.split(r"\n##\s+", md):
    if not part.strip(): continue
    title = part.splitlines()[0].lstrip("# ").strip()
    body = "\n".join(part.splitlines()[1:])
    secoes.append({"titulo": title[:90], "html": md2html(body)})

ctx = {
    "classificacao": "CONFIDENCIAL — USO INTERNO (controle externo)",
    "titulo": "Veredito Forense — Contrato 005/2021 ITERJ × MGS Clean",
    "subtitulo": "Auditoria independente (SIAFE + árvore SEI OCR) · 4 perguntas respondidas · ASSCONT testado",
    "data": datetime.now().strftime("%d/%m/%Y"), "analista": "JFN — Núcleo de Fiscalização (multi-agente)",
    "metodologia": "Bateria T01-T22 · reconciliação SIAFE↔DB · leitura OCR de 30 docs SEI · verificação adversarial · padrão Kroll",
    "score": 55, "faixa": "MÉDIO",
    "top_flags": ["ASSCONT: erro aritmético '×4' confirmado", "Glosa R$21k = bruto×líquido (crédito-fantasma)",
                  "Duplo-Novembro/2025 R$102.902,89×2 (pode inverter o saldo)", "Saldo R$56k SUPERDIMENSIONADO"],
    "secoes": secoes,
    "proveniencia": [{"dado": "55 OBs + 30 docs SEI OCR'd", "estado": "REAL", "fonte": "SIAFE direto + árvore SEI (itkava)", "data": "19/06/2026"}],
    "ressalva": "Indício ≠ acusação; INDISPONÍVEL ≠ irregular; só a OB Contabilizado é paga. Conformidade SUSPENSA até NFs + planilha.",
}
nome = f"veredito_forense_iterj_mgs_{datetime.now().date()}"
destino = str(REPO / "reports" / f"{nome}.pdf")
asyncio.run(html_to_pdf(render_html(ctx), destino))
print("PDF:", destino, Path(destino).stat().st_size, "bytes")

def key(n):
    m = re.search(rf"^{n}=(.+)$", ENV.read_text(), re.M); return m.group(1).strip().strip('"').strip("'") if m else ""
tok, chat = key("TELEGRAM_BOT_TOKEN"), key("TELEGRAM_CHAT_ID"); base = f"https://api.telegram.org/bot{tok}"
msg = ("⚖️ *VEREDITO FORENSE — ITERJ × MGS (contrato 005/2021)*\n"
       "_Auditoria independente: SIAFE + árvore SEI (30 docs OCR'd) + bateria T01-T22, verificada._\n\n"
       "*55 OBs, R$ 5.038.369,24 — todas pagas, reconciliadas ao centavo. NADA confirmado como irregular.*\n\n"
       "*As 4 perguntas:*\n"
       "1️⃣ *Direção da dívida:* INDETERMINADA. O \"Estado deve R$56k à MGS\" do órgão *não se sustenta*.\n"
       "2️⃣ *2023:* repactuação regular; *nenhum pagamento a maior demonstrável*.\n"
       "3️⃣ *Repactuação 2025:* o retroativo Mar–Jun/25 (R$35.014,96) está *em aberto e devido em princípio* (mas é teto bruto).\n"
       "4️⃣ *Saldo R$56k:* ❌ *ERRADO* — superdimensionado.\n\n"
       "*Achados 🔴 contra a conta do órgão:*\n"
       "• Erro aritmético no relatório: \"4× 118.441,47\" = 473.765,88, *não* 586.950,02 (são 5 parcelas).\n"
       "• A \"glosa\" de R$21.029,32 é *crédito-fantasma*: 113.184,14 é o *bruto de uma NF normal* (102.902,89 líq + INSS + IR), não fatura reduzida.\n"
       "• *Duplo-Novembro/2025* (R$102.902,89 ×2): se for o mesmo mês 2×, *inverte o saldo* (MGS deve ~R$103k ao Estado).\n\n"
       "*Crédito real da MGS, se houver: ≤ ~R$35 mil bruto — só fecha com as NFs e a planilha (no processo da contratação).*\n"
       "📎 Veredito completo no PDF.")
print("msg:", httpx.post(f"{base}/sendMessage", data={"chat_id": chat, "text": msg, "parse_mode": "Markdown"}, timeout=30).json().get("ok"))
with open(destino, "rb") as f:
    print("pdf:", httpx.post(f"{base}/sendDocument", data={"chat_id": chat, "caption": "Veredito forense ITERJ×MGS (PDF)"},
          files={"document": ("veredito_forense_iterj_mgs.pdf", f, "application/pdf")}, timeout=60).json().get("ok"))
