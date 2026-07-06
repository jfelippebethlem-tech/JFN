#!/bin/bash
# Sweep HISTÓRICO de benefícios (Novo Bolsa Família + BPC) × nomeados da Câmara.
# Objetivo do dono (2026-07-05): saber se recebiam benefício DURANTE a nomeação, com datas.
# Roda 1 competência por vez (VM 2 vCPU: download+stream+apaga), do mais recente p/ trás.
# Pula competência já coletada. Novo Bolsa Família só existe desde 2023-03; antes disso o
# download falha e fica registrado no log (Auxílio Brasil/BF antigo = fase 2, formato difere).
set -u
cd /home/ubuntu/JFN || exit 1
PY=.venv/bin/python
DB=data/pcrj_benef.db

for ym in 202604 202603 202602 202601 \
          202512 202511 202510 202509 202508 202507 202506 202505 202504 202503 202502 202501 \
          202412 202411 202410 202409 202408 202407 202406 202405 202404 202403 202402 202401 \
          202312 202311 202310 202309 202308 202307 202306 202305 202304 202303 202302 202301; do
  ja=$($PY - <<EOF
import sqlite3
try:
    con=sqlite3.connect("file:$DB?mode=ro",uri=True)
    print(con.execute("select count(*) from pcrj_beneficio where competencia='$ym'").fetchone()[0])
except Exception: print(0)
EOF
)
  if [ "${ja:-0}" -gt 0 ]; then echo "[sweep] $ym já coletado ($ja linhas) — pulo"; continue; fi
  # não competir com a VM ocupada (sweeps SEI/SIAFE etc.)
  while [ "$(awk '{print ($1>1.8)}' /proc/loadavg)" = "1" ]; do echo "[sweep] load alto, aguardo 120s"; sleep 120; done
  echo "[sweep] === $ym ==="
  $PY -m compliance_agent.pcrj.beneficio_pcrj "$ym"
  sleep 10
done
echo "[sweep] FIM"
