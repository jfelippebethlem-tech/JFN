#!/bin/bash
# sweeps_serial <lane> — orquestrador de sweeps por LANE. Roda em SÉRIE dentro da lane; até 2 lanes em
# paralelo (browser + dados) usam bem os 2 cores da VM SEM a contenção de 4-way (§8: a VM já caiu).
#   lane=browser → SEI + CPF (preso ao Chromium; serial interno via browser_lock_async)
#   lane=dados   → endereço → benefícios → fachada (DB/rede; busy_timeout evita lock)
#   lane=all     → tudo em série (fallback 1-lane)
# Resumível (cada sweep tem checkpoint). Serviço systemd (auto-restart). Pausas: data/.pause_sweeps (tudo) ·
# data/.pause_{sei,endereco,beneficios,fachada}_sweep (individual).
set -u
LANE="${1:-all}"
cd /home/ubuntu/JFN || exit 1
export PYTHONPATH=.
PY=.venv/bin/python
LOG="data/sweeps_serial_${LANE}.log"
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

do_sei(){
  [ -f data/.pause_sei_sweep ] && return
  say "SEI: lote (--max 10)"; timeout 1800 $PY -m tools.sei_sweep --max 10 >> data/sei_cache/sei_sweep_loop.out 2>&1 || say "SEI rc=$?"
  CPFOUT=$(timeout 600 $PY -m tools.sei_cpf_sweep 2>&1 | tail -1); say "CPF: $CPFOUT"
}
do_endereco(){
  [ -f data/.pause_endereco_sweep ] && return
  say "endereço: lote (100)"; timeout 900 $PY -m tools.backfill_verificacao_endereco --limite 100 --pausa 0.4 >> data/endereco_serial.log 2>&1 || say "endereço rc=$?"
}
do_beneficios(){
  [ -f data/.pause_beneficios_sweep ] && return
  say "benefícios: lote (400)"; timeout 1200 $PY -m tools.beneficios_sweep --limite 400 --pausa 0.3 >> data/beneficios_serial.log 2>&1 || say "benefícios rc=$?"
}
do_fachada(){
  [ -f data/.pause_fachada_sweep ] && return
  say "fachada: 1 UG"; timeout 1200 bash tools/fachada_sweep_rotativo.sh >> data/dd_sweep/cron.log 2>&1 || say "fachada rc=$?"
}

say "lane '$LANE' iniciada (PID $$)"
while true; do
  if [ -f data/.pause_sweeps ]; then sleep 120; continue; fi
  L=$(awk '{print int($1)}' /proc/loadavg)
  if [ "$L" -ge 5 ]; then say "load $L alto — espera 120s"; sleep 120; continue; fi
  case "$LANE" in
    browser) do_sei ;;
    dados)   do_fachada; do_beneficios; do_endereco ;;   # rápidos/cacheados primeiro; endereço (OSM lento) por último
    *)       do_sei; do_endereco; do_beneficios; do_fachada ;;
  esac
  sleep 10
done
