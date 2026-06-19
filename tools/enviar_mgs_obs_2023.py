#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sweep MGS Clean 2023 (OBs tfe_ob) -> documento formatado + envio Telegram (Yoda)."""
import re
import sqlite3
from pathlib import Path

import httpx

CNPJ = "19088605000104"
ANO = "2023"
DB = Path("/home/ubuntu/JFN/data/compliance.db")
ENV = Path("/home/ubuntu/.hermes/.env")
OUT = Path("/home/ubuntu/JFN/reports/mgs_clean_obs_2023.txt")


def key(name):
    m = re.search(rf"^{name}=(.+)$", ENV.read_text(), re.M)
    return m.group(1).strip().strip('"').strip("'") if m else ""


def brl(v):
    s = f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


c = sqlite3.connect(DB)
rows = c.execute(
    """SELECT numero_ob, data_pagamento, ug_nome, valor, observacao
       FROM ordens_bancarias
       WHERE categoria='tfe_ob' AND exercicio=? AND favorecido_cpf=?
       ORDER BY data_pagamento, numero_ob""",
    (ANO, CNPJ),
).fetchall()

total = sum(r[3] for r in rows)
por_ug = {}
for r in rows:
    por_ug[r[2]] = por_ug.get(r[2], [0, 0.0])
    por_ug[r[2]][0] += 1
    por_ug[r[2]][1] += r[3]

# ---------- documento .txt (deliverable) ----------
L = []
L.append("=" * 92)
L.append("ORDENS BANCARIAS (PAGAMENTOS) — MGS CLEAN SOLUCOES E SERVICOS LTDA")
L.append("CNPJ 19.088.605/0001-04  |  Exercicio 2023  |  Fonte: TFE/SIAFE-Rio (espelho D-1)")
L.append("=" * 92)
L.append(f"Total de OBs: {len(rows)}        Total pago (liquidacao): R$ {brl(total)}")
L.append("Nota: OB = pagamento efetivo (liquidacao). Empenho != OB.")
L.append("")
L.append("RESUMO POR ORGAO PAGADOR")
L.append("-" * 92)
for ug, (n, v) in sorted(por_ug.items(), key=lambda x: -x[1][1]):
    L.append(f"  {ug[:64]:<64} {n:>3} OBs   R$ {brl(v):>16}")
L.append("")
L.append("DETALHAMENTO DAS OBs")
L.append("-" * 92)
L.append(f"{'OB':<13} {'DATA':<11} {'VALOR (R$)':>16}  ORGAO / HISTORICO")
L.append("-" * 92)
for ob, data, ug, valor, obs in rows:
    obs = re.sub(r"\s+", " ", (obs or "").strip())
    L.append(f"{ob:<13} {data:<11} {brl(valor):>16}  {ug[:60]}")
    if obs:
        L.append(f"{'':>42}  {obs[:140]}")
L.append("=" * 92)
L.append(f"TOTAL GERAL: {len(rows)} OBs  —  R$ {brl(total)}")
L.append("=" * 92)
OUT.write_text("\n".join(L), encoding="utf-8")

# ---------- mensagem resumo ----------
linhas_ug = "\n".join(
    f"• {ug[:42]} — {n} OBs · R$ {brl(v)}"
    for ug, (n, v) in sorted(por_ug.items(), key=lambda x: -x[1][1])
)
msg = (
    f"🧾 *Sweep MGS Clean — Ordens Bancárias 2023*\n"
    f"CNPJ 19.088.605/0001-04\n\n"
    f"*{len(rows)} OBs* · Total pago: *R$ {brl(total)}*\n"
    f"_(OB = pagamento/liquidação; empenho ≠ OB)_\n\n"
    f"*Por órgão pagador:*\n{linhas_ug}\n\n"
    f"📎 Detalhamento completo das {len(rows)} OBs no arquivo anexo."
)

token = key("TELEGRAM_BOT_TOKEN")
chat = key("TELEGRAM_CHAT_ID")
base = f"https://api.telegram.org/bot{token}"

r1 = httpx.post(
    f"{base}/sendMessage",
    data={"chat_id": chat, "text": msg, "parse_mode": "Markdown"},
    timeout=30,
)
print("sendMessage:", r1.status_code, r1.json().get("ok"))

with open(OUT, "rb") as f:
    r2 = httpx.post(
        f"{base}/sendDocument",
        data={"chat_id": chat, "caption": f"MGS Clean — {len(rows)} OBs 2023 (R$ {brl(total)})"},
        files={"document": ("mgs_clean_obs_2023.txt", f, "text/plain")},
        timeout=60,
    )
print("sendDocument:", r2.status_code, r2.json().get("ok"))
print("doc:", OUT)
