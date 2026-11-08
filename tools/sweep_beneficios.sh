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

# MESES CALCULADOS PELA DATA (2026-10-12). A lista era fixa e terminava em 202604: nenhum mês novo
# entrava, e o pcrj_benef.db parou em 202605 (rodado à mão). Do mês passado até 2023-01; o Portal
# publica com ~2 meses de atraso, então os meses mais novos falham no download e são tentados de
# novo no próximo disparo (coletar() não apaga nada quando nenhum download funciona).
MESES=$($PY -c "
from datetime import date
y, m = date.today().year, date.today().month
out = []
while (y, m) >= (2023, 1):
    m -= 1
    if m == 0: y, m = y - 1, 12
    if (y, m) >= (2023, 1): out.append(f'{y}{m:02d}')
print(' '.join(out))")
for ym in $MESES; do
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
  esperas=0
  while [ "$(awk '{print ($1>1.8)}' /proc/loadavg)" = "1" ]; do
    esperas=$((esperas + 1)); [ "$esperas" -gt 15 ] && { echo "[sweep] load alto há 30 min — encerro, próximo disparo retoma"; exit 0; }
    echo "[sweep] load alto, aguardo 120s"; sleep 120
  done
  echo "[sweep] === $ym ==="
  $PY -m compliance_agent.pcrj.beneficio_pcrj "$ym"
  sleep 10
done
echo "[sweep] FIM"
