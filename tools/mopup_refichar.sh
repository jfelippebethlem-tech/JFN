#!/bin/bash
set -u; cd /home/ubuntu/JFN || exit 1; export PYTHONPATH=.
PY=.venv/bin/python; LOG=data/mopup_refichar.log; PRIO="nice -n 10 ionice -c2 -n6"
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
say "=== mopup: refichar faltantes (situacao) -> depurar -> arvore -> direc ==="
$PRIO $PY -m tools.sei_refichar >> "$LOG" 2>&1; say "refichar rc=$?"
$PRIO timeout 600 $PY -m tools.sei_depurar_db >> "$LOG" 2>&1; say "depurar rc=$?"
$PRIO timeout 900 $PY -m tools.sei_arvore_build >> "$LOG" 2>&1; say "arvore rc=$?"
$PRIO timeout 400 $PY -m tools.sei_direcionamento_varre >> "$LOG" 2>&1; say "direc rc=$?"
say "=== mopup FIM ==="
