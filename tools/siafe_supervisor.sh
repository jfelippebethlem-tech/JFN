#!/bin/bash
# siafe_supervisor — mantém os sweeps SIAFE 1 e 2 VIVOS até concluírem.
# Os sweeps morrem por crash do driver Playwright/chromium (emitErrorCloseNT) em runs longos; como são
# RESUMÍVEIS (checkpoint UG:ano + sub-prefixo), basta relançar que continuam de onde pararam.
# Para quando ambos logarem "SWEEP COMPLETO". Avisa no Telegram ao fim. Rodar via nohup (é bash, não trava).
cd /home/jfelippebethlem/JFN || exit 1
LOG=data/siafe_supervisor.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
done_sys(){ # $1=sistema → 0 se concluído (log diz SWEEP COMPLETO e processo não roda)
  pgrep -f "siafe_sweep_full $1" >/dev/null && return 1
  tail -5 "data/siafe_sweep_full_$1.log" 2>/dev/null | grep -q "SWEEP COMPLETO" && return 0
  return 1
}
say "supervisor iniciado"
while true; do
  for S in 2 1; do
    if [ -f "data/.pause_sweep_$S" ]; then continue; fi   # pausa manual (ex.: fix do §41 em andamento)
    if done_sys "$S"; then continue; fi
    if ! pgrep -f "siafe_sweep_full $S" >/dev/null; then
      rm -f data/sei_cache/siafe_lock.json 2>/dev/null   # limpa lock obsoleto do processo morto
      PYTHONPATH=. .venv/bin/python -m tools.siafe_sweep_full "$S" >> "data/siafe_sweep_full_$S.out" 2>&1 &
      say "relançou sweep $S (pid $!)"
      sleep 15
    fi
  done
  if done_sys 2 && done_sys 1; then
    say "AMBOS os sweeps concluídos → rodando análise pós-sweep"
    # roda a ANÁLISE PÓS-SWEEP automática (VACUUM + análise + avisa no Telegram). Marcador evita rodar 2x.
    if [ ! -f data/.pos_sweep_feito ]; then
      PYTHONPATH=. /home/jfelippebethlem/JFN/.venv/bin/python -m tools.pos_sweep_analise >> data/pos_sweep_analise.out 2>&1
      touch data/.pos_sweep_feito
      say "análise pós-sweep concluída (ver docs/ANALISE-POS-SWEEP-*.md)"
    fi
    break
  fi
  sleep 180
done
say "supervisor encerrado"
