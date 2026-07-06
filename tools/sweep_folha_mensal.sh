#!/bin/bash
# Carrega a folha da Prefeitura MÊS A MÊS (ArquivoTC), para tenure precisa (nomeação/exoneração por
# mês) e checagem justa de benefício-durante-vínculo. ~60 meses × ~22MB. Resumível (pula já carregado).
set -u
cd /home/ubuntu/JFN || exit 1
PY=.venv/bin/python
DBP=data/pcrj.db
for ano in 2021 2022 2023 2024 2025 2026; do
  for m in 01 02 03 04 05 06 07 08 09 10 11 12; do
    ym="${ano}${m}"
    [ "$ym" -lt 202106 ] && continue
    [ "$ym" -gt 202605 ] && continue
    ja=$($PY - <<EOF
import sqlite3
try:
    c=sqlite3.connect("file:$DBP?mode=ro",uri=True)
    print(c.execute("select count(*) from pcrj_folha_pref where competencia='$ym'").fetchone()[0])
except Exception: print(0)
EOF
)
    [ "${ja:-0}" -gt 0 ] && { echo "[folha-mensal] $ym já carregado ($ja) — pulo"; continue; }
    while [ "$(awk '{print ($1>1.8)}' /proc/loadavg)" = "1" ]; do sleep 90; done
    $PY -m compliance_agent.pcrj.folha_pref "$ym"
    sleep 3
  done
done
echo "[folha-mensal] FIM"
