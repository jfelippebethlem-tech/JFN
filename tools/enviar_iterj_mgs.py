#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ITERJ (UG 133100) -> MGS Clean: todas as OBs por ano (SIAFE 1+2 unificados) -> Yoda/Telegram."""
import re
import sqlite3
from pathlib import Path
import httpx

CNPJ = "19088605000104"
UG = "133100"
DB = Path("/home/ubuntu/JFN/data/compliance.db")
ENV = Path("/home/ubuntu/.hermes/.env")
OUT = Path("/home/ubuntu/JFN/reports/iterj_mgs_obs_por_ano.txt")
# Qual sistema-fonte cobre cada exercicio (espelho TFE consolida ambos)
SISTEMA = {y: ("SIAFE 1" if y <= 2023 else "SIAFE 2") for y in range(2016, 2027)}


def key(n):
    m = re.search(rf"^{n}=(.+)$", ENV.read_text(), re.M)
    return m.group(1).strip().strip('"').strip("'") if m else ""


def brl(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


c = sqlite3.connect(DB)
rows = c.execute(
    """SELECT exercicio, numero_ob, data_pagamento, valor, favorecido_nome, observacao
       FROM ordens_bancarias
       WHERE ug_codigo=? AND favorecido_cpf=?
       ORDER BY data_pagamento, numero_ob""",
    (UG, CNPJ),
).fetchall()

por_ano = {}
for ex, ob, dt, val, nome, obs in rows:
    por_ano.setdefault(ex, []).append((ob, dt, val, obs))
total = sum(r[3] for r in rows)

L = []
L.append("=" * 94)
L.append("PAGAMENTOS DO ITERJ À MGS CLEAN — ORDENS BANCÁRIAS (OBs) POR EXERCÍCIO")
L.append("Pagador: INST. DE TERRAS E CARTOGR. DO EST. RJ (ITERJ) — UG 133100")
L.append("Favorecido: MGS CLEAN SOLUÇÕES E SERVIÇOS — CNPJ 19.088.605/0001-04")
L.append("Objeto (recorrente): limpeza, higiene, conservação, copeiragem, recepção")
L.append("Fonte: TFE/SIAFE-Rio (espelho D-1, consolida SIAFE 1 e SIAFE 2)")
L.append("=" * 94)
L.append(f"TOTAL: {len(rows)} OBs   —   R$ {brl(total)}")
L.append("Nota: OB = pagamento efetivo (liquidação). Empenho ≠ OB.")
L.append("")
L.append("RESUMO POR ANO")
L.append("-" * 94)
L.append(f"{'ANO':<6} {'SISTEMA':<9} {'OBs':>4} {'VALOR PAGO (R$)':>20}")
for ex in sorted(por_ano):
    obs = por_ano[ex]
    L.append(f"{ex:<6} {SISTEMA.get(ex,'-'):<9} {len(obs):>4} {brl(sum(o[2] for o in obs)):>20}")
L.append("-" * 94)
L.append(f"{'TOTAL':<16} {len(rows):>4} {brl(total):>20}")
L.append("")
L.append("DETALHAMENTO DAS OBs POR ANO")
L.append("=" * 94)
for ex in sorted(por_ano):
    obs = por_ano[ex]
    L.append("")
    L.append(f"━━ {ex}  ({SISTEMA.get(ex,'-')})  —  {len(obs)} OBs  —  R$ {brl(sum(o[2] for o in obs))}")
    L.append(f"   {'OB':<13} {'DATA':<11} {'VALOR (R$)':>15}  OBJETO")
    for ob, dt, val, o in obs:
        o = re.sub(r"\s+", " ", (o or "").strip())[:78]
        L.append(f"   {ob:<13} {dt:<11} {brl(val):>15}  {o}")
L.append("")
L.append("=" * 94)
L.append("COBERTURA / HONESTIDADE")
L.append("- 1º pagamento ITERJ→MGS: 2022-01-25. A base tem dados do ITERJ desde 2019;")
L.append("  2019–2021 NÃO registram OB do ITERJ à MGS (contrato iniciou em 2022).")
L.append("- 2016–2018: fora da cobertura do espelho TFE (INDISPONÍVEL ≠ R$ 0).")
L.append("  Só uma varredura direta no SIAFE 1 confirmaria esses 3 anos, se necessário.")
L.append("=" * 94)
OUT.write_text("\n".join(L), encoding="utf-8")

linhas = "\n".join(
    f"• {ex} ({SISTEMA.get(ex,'-')}) — {len(por_ano[ex])} OBs · R$ {brl(sum(o[2] for o in por_ano[ex]))}"
    for ex in sorted(por_ano)
)
msg = (
    f"🏛️ *ITERJ → MGS Clean — Ordens Bancárias por ano*\n"
    f"ITERJ (UG 133100) · MGS CNPJ 19.088.605/0001-04\n\n"
    f"*{len(rows)} OBs* · Total pago: *R$ {brl(total)}*\n"
    f"_Objeto: limpeza/conservação/copeiragem/recepção_\n\n"
    f"*Por ano (SIAFE 1+2 unificados):*\n{linhas}\n\n"
    f"⚠️ Contrato iniciou em 2022; 2019–2021 sem OB ITERJ→MGS na base; "
    f"2016–2018 fora da cobertura TFE.\n"
    f"📎 Detalhe das {len(rows)} OBs no anexo."
)

token, chat = key("TELEGRAM_BOT_TOKEN"), key("TELEGRAM_CHAT_ID")
base = f"https://api.telegram.org/bot{token}"
r1 = httpx.post(f"{base}/sendMessage", data={"chat_id": chat, "text": msg, "parse_mode": "Markdown"}, timeout=30)
print("sendMessage:", r1.status_code, r1.json().get("ok"))
with open(OUT, "rb") as f:
    r2 = httpx.post(f"{base}/sendDocument",
                    data={"chat_id": chat, "caption": f"ITERJ→MGS — {len(rows)} OBs (R$ {brl(total)})"},
                    files={"document": ("iterj_mgs_obs_por_ano.txt", f, "text/plain")}, timeout=60)
print("sendDocument:", r2.status_code, r2.json().get("ok"))
print("doc:", OUT)
