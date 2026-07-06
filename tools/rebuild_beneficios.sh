#!/bin/bash
# Reconstrói a base de benefícios com o ALVO COMPLETO (Câmara + folha completa da Prefeitura).
# 1) carrega retratos anuais da folha da Prefeitura (amplia o alvo no tempo);
# 2) limpa pcrj_beneficio (estava com alvo parcial);
# 3) recruza TODAS as competências 2020–2026 (o módulo baixa só os programas vigentes em cada mês).
# VM-safe: 1 download por vez, guard de carga. Resumível: pula competência já coletada.
set -u
cd /home/ubuntu/JFN || exit 1
PY=.venv/bin/python
DBP=data/pcrj.db
DBB=data/pcrj_benef.db

echo "[rebuild] $(date '+%F %T') carregando retratos da folha da Prefeitura"
for ym in 202605 202412 202312 202212 202112 202012; do
  ja=$($PY - <<EOF
import sqlite3
try:
    c=sqlite3.connect("file:$DBP?mode=ro",uri=True)
    print(c.execute("select count(*) from pcrj_folha_pref where competencia='$ym'").fetchone()[0])
except Exception: print(0)
EOF
)
  [ "${ja:-0}" -gt 0 ] && { echo "[rebuild] folha $ym já carregada ($ja) — pulo"; continue; }
  $PY -m compliance_agent.pcrj.folha_pref "$ym"
  sleep 5
done

echo "[rebuild] limpando pcrj_beneficio (alvo parcial antigo)"
$PY - <<EOF
import sqlite3
c=sqlite3.connect("$DBB"); c.execute("DELETE FROM pcrj_beneficio"); c.commit(); c.close()
print("pcrj_beneficio limpo")
EOF

echo "[rebuild] recruzando benefícios 2020–2026 com alvo completo"
meses=""
for ano in 2026 2025 2024 2023 2022 2021 2020; do
  for m in 12 11 10 09 08 07 06 05 04 03 02 01; do meses="$meses ${ano}${m}"; done
done
for ym in $meses; do
  { [ "$ym" -gt 202605 ] || [ "$ym" -lt 202004 ]; } && continue
  ja=$($PY - <<EOF
import sqlite3
try:
    c=sqlite3.connect("file:$DBB?mode=ro",uri=True)
    print(c.execute("select count(*) from pcrj_beneficio where competencia='$ym'").fetchone()[0])
except Exception: print(0)
EOF
)
  [ "${ja:-0}" -gt 0 ] && { echo "[rebuild] $ym já coletado ($ja) — pulo"; continue; }
  while [ "$(awk '{print ($1>1.8)}' /proc/loadavg)" = "1" ]; do echo "[rebuild] load alto, aguardo 120s"; sleep 120; done
  echo "[rebuild] === $ym ==="
  $PY -m compliance_agent.pcrj.beneficio_pcrj "$ym"
  sleep 8
done
echo "[rebuild] FIM $(date '+%F %T')"
