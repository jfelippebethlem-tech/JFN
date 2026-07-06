#!/bin/bash
# FASE 2 do sweep de benefícios: janela 2020–2022 (Auxílio Emergencial abr/2020–out/2021 e
# Auxílio Brasil nov/2021–dez/2022). A fase 1 (2023→2026, BF/BPC) cobre o resto.
# Encadeada: espera a fase 1 terminar (se estiver rodando) p/ não competir por banda.
# Arquivos grandes (Emergencial ~615MB/mês, Brasil ~318MB/mês) — stream+filtra+apaga, 1 por vez.
set -u
cd /home/ubuntu/JFN || exit 1
PY=.venv/bin/python
DB=data/pcrj_benef.db

# espera a fase 1 (se viva) — no máx algumas horas
for _ in $(seq 1 240); do
  if pgrep -f 'sweep_beneficios.sh' >/dev/null 2>&1; then sleep 60; else break; fi
done
echo "[fase2] iniciando janela 2020–2022"

meses=""
for ano in 2022 2021 2020; do
  for m in 12 11 10 09 08 07 06 05 04 03 02 01; do meses="$meses ${ano}${m}"; done
done
for ym in $meses; do
  # só 202004..202212 têm Emergencial/Brasil; fora disso o coletar baixa só BPC (ok, mas pulamos <202004)
  [ "$ym" -lt 202004 ] && continue
  ja=$($PY - <<EOF
import sqlite3
try:
    con=sqlite3.connect("file:$DB?mode=ro",uri=True)
    print(con.execute("select count(*) from pcrj_beneficio where competencia='$ym'").fetchone()[0])
except Exception: print(0)
EOF
)
  if [ "${ja:-0}" -gt 0 ]; then echo "[fase2] $ym já coletado ($ja) — pulo"; continue; fi
  while [ "$(awk '{print ($1>1.8)}' /proc/loadavg)" = "1" ]; do echo "[fase2] load alto, aguardo 120s"; sleep 120; done
  echo "[fase2] === $ym ==="
  $PY -m compliance_agent.pcrj.beneficio_pcrj "$ym"
  sleep 10
done
echo "[fase2] FIM"
