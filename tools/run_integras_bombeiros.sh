#!/bin/bash
# Envia a ÍNTEGRA (PDF de todos os docs) dos processos suspeitos dos bombeiros ao Telegram do dono.
# Serializa com o sweep (este roda com .pause_bombeiros setado; despausa no fim).
cd /home/ubuntu/JFN || exit 1
PY=".venv/bin/python"; export PYTHONPATH=.
LOG=data/bombeiros_integra.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
say "início íntegras suspeitos"
for PROC in "270006/012128/2024" "270006/006444/2024" "270003/002373/2024"; do
  say "ÍNTEGRA $PROC ..."
  timeout 700 $PY tools/sei_integra_completa.py "$PROC" >> "$LOG" 2>&1
  say "$PROC rc=$?"
  sleep 5
done
rm -f data/.pause_bombeiros
say "FIM — sweep despausado"
