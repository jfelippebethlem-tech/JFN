#!/usr/bin/env bash
# sweep_sede.sh — resume VM-safe da verificação de sede via Google (flock single-instance).
# Roda 1 passada bounded; o quota-guard (9999/31d por API) e o time-bound param sozinhos; resumível.
# Cron sugerido (a cada 2h, finaliza a base ao longo do mês dentro da cota grátis):
#   0 */2 * * *  /home/jfelippebethlem/JFN/tools/sweep_sede.sh >> /home/jfelippebethlem/JFN/data/sweep_sede.log 2>&1
set -u
cd /home/jfelippebethlem/JFN || exit 1
[ -f data/.pause_sede_sweep ] && { echo "$(date -Is) pausado (.pause_sede_sweep)"; exit 0; }
# load-guard: VM de 2 vCPU sem swap — não empilhar
L=$(awk '{print int($1)}' /proc/loadavg)
[ "${L:-0}" -ge 4 ] && { echo "$(date -Is) load alto ($L) — pula"; exit 0; }
exec flock -n data/.sweep_sede.lock \
  nice -n10 ionice -c2 -n6 timeout 9000 \
  .venv/bin/python -m tools.sweep_sede_google --max-horas 2.4 --pausa 0.1
