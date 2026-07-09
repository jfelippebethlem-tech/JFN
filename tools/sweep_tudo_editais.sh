#!/bin/bash
# Campanha "sweep de tudo" p/ editais — bounded, resumível, parável, VM-safe, SESSÃO ÚNICA (espera o cron/bombeiros
# liberar; o cron pula quando este roda). Prioriza --seguir-pais (processo-pai de contratação = EDITAL) + geral.
# Parar: `touch /home/ubuntu/JFN/data/.stop_sweep_tudo`. Pausar tudo: `touch data/.pause_sweeps`.
set -u
cd /home/ubuntu/JFN || exit 1
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/sweep_tudo_editais.log
FIND=data/sweep_tudo_achados.log
STOP=data/.stop_sweep_tudo
MAXITER="${1:-24}"          # nº de ciclos (default 24; cada ciclo ~lê ~16 processos)
PRIO="nice -n 12 ionice -c2 -n7"
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

rm -f "$STOP"
say "=== INÍCIO campanha sweep de tudo (MAXITER=$MAXITER) ==="
for i in $(seq 1 "$MAXITER"); do
  [ -f "$STOP" ] && { say "STOP flag — encerrando no ciclo $i"; break; }
  [ -f data/.pause_sweeps ] && { say "pausado (.pause_sweeps) — encerrando"; break; }
  # backstop VM: load alto → espera
  L=$(awk '{print int($1)}' /proc/loadavg); if [ "$L" -ge 4 ]; then say "load $L alto — espera 60s"; sleep 60; fi
  # sessão única: espera qualquer sweep/reader vivo terminar (até ~20 min)
  for w in $(seq 1 40); do
    pgrep -f 'tools\.sei_swee[p]|sei_bombeiros_swee[p]|tools\.sei_proc_paginad[o]|tools\.sei_reade[r]' >/dev/null \
      && { sleep 30; } || break
  done
  say "ciclo $i/$MAXITER: seguir-pais (editais)"
  $PRIO timeout 900 $PY -m tools.sei_sweep --seguir-pais --max 6 >>"$LOG" 2>&1; say "  seguir-pais rc=$?"
  # nova espera curta (o cron pode ter pego o lane no intervalo)
  for w in $(seq 1 20); do pgrep -f 'tools\.sei_swee[p]|sei_bombeiros' >/dev/null && sleep 30 || break; done
  say "ciclo $i/$MAXITER: geral --max 12"
  $PRIO timeout 1200 $PY -m tools.sei_sweep --max 12 >>"$LOG" 2>&1; say "  geral rc=$?"
  # a cada 3 ciclos, roda o motor nos editais recém-cacheados e registra achados E1/E7 (não E2/J2 pré-existentes)
  if [ $((i % 3)) -eq 0 ]; then
    say "  motor nos editais cacheados (ciclo $i)"
    $PRIO $PY /tmp/claude-1001/-home-ubuntu/5385bc93-a79e-4e98-a434-a3e47adf63ed/scratchpad/motor_editais_cache.py \
      >>"$FIND" 2>&1; echo "  [$(date '+%F %T')] --- fim motor ciclo $i ---" >> "$FIND"
  fi
done
say "=== FIM campanha (motor final) ==="
$PY /tmp/claude-1001/-home-ubuntu/5385bc93-a79e-4e98-a434-a3e47adf63ed/scratchpad/motor_editais_cache.py >>"$FIND" 2>&1
say "=== motor final OK ==="
