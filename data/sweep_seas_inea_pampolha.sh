#!/bin/bash
# SWEEP do pente-fino SEAS+INEA na gestão Pampolha (2021-2024): (1) coleta as OBs orçamentárias RICAS
# (com nº de processo SEI) dessas UGs — SIAFE-1 (www5) p/ 2021-2023 e SIAFE-2 p/ 2024; (2) lê os
# processos SEI correlacionados (sei_sweep --ug, limitado). Serializado (1 browser por vez), VM-safe,
# resumível. Reporta no Telegram ao fim de cada fase. NÃO roda 2024 no SIAFE-1 (lição: só até 2023 lá).
set -u
cd /home/ubuntu/JFN || exit 1
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/sweep_seas_inea.log
SIAFE1="https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"
UGS=(240100 240200 243200)
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

livre(){ for _ in $(seq 1 240); do
  pgrep -f "sei_sweep|sei_integra_completa|siafe_ob_orcamentaria|siafe_runner" >/dev/null 2>&1 && sleep 30 || return 0
done; return 1; }

say "=== SWEEP SEAS+INEA Pampolha: INÍCIO ==="
# FASE 1 — SIAFE orçamentária (nº de processo SEI): 2021-2023 no SIAFE-1, 2024 no SIAFE-2
for UG in "${UGS[@]}"; do
  for ANO in 2021 2022 2023; do
    livre; say "SIAFE-1 UG$UG $ANO"
    JFN_SIAFE_LOGIN_URL="$SIAFE1" timeout 900 $PY -m compliance_agent.siafe_runner ug "$UG" "$ANO" >> "$LOG" 2>&1
    sleep 8
  done
  livre; say "SIAFE-2 UG$UG 2024"
  timeout 900 $PY -m compliance_agent.siafe_runner ug "$UG" 2024 >> "$LOG" 2>&1
  sleep 8
done

# relatório da FASE 1: quantos processos SEI novos temos por UG
$PY - <<'PY' >> "$LOG" 2>&1
import sqlite3, os, re, asyncio
c=sqlite3.connect('file:data/compliance.db?mode=ro',uri=True)
L=["🛰️ *Sweep SEAS+INEA (Pampolha) — Fase 1 (OBs orçamentárias c/ processo SEI)*"]
for ug,nome in (('240100','SEAS'),('240200','SEA-PSAM'),('243200','INEA')):
    for ano in (2021,2022,2023,2024):
        n=c.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente=? AND exercicio=?",(ug,ano)).fetchone()[0]
        p=c.execute("SELECT COUNT(DISTINCT processo) FROM ob_orcamentaria_siafe WHERE ug_emitente=? AND exercicio=? AND processo IS NOT NULL AND processo!=''",(ug,ano)).fetchone()[0]
        if n: L.append(f"• UG{ug} {nome} {ano}: {n} OBs, {p} processos SEI distintos")
c.close()
for ln in open('.env',encoding='utf-8',errors='replace'):
    m=re.match(r'^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$',ln)
    if m: os.environ.setdefault(m.group(1),m.group(2).strip().strip('"').strip("'"))
os.environ["TELEGRAM_CHAT_ID"]=os.environ.get("TELEGRAM_OWNER_ID","")
from compliance_agent.notifications.telegram import enviar_mensagem
asyncio.run(enviar_mensagem("\\n".join(L), chat_id=os.environ.get("TELEGRAM_OWNER_ID","")))
PY
say "FASE 1 concluída"

# FASE 2 — lê os processos SEI correlacionados às OBs de SEAS e INEA (limitado; degrada honesto)
for UG in 240100 243200; do
  livre; say "sei_sweep --ug $UG"
  timeout 3600 $PY -m tools.sei_sweep --ug "$UG" --max 40 >> "$LOG" 2>&1
  sleep 10
done
say "=== SWEEP SEAS+INEA Pampolha: FIM ==="
