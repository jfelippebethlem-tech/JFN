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
    if done_sys "$S"; then continue; fi
    if ! pgrep -f "siafe_sweep_full $S" >/dev/null; then
      rm -f data/sei_cache/siafe_lock.json 2>/dev/null   # limpa lock obsoleto do processo morto
      PYTHONPATH=. .venv/bin/python -m tools.siafe_sweep_full "$S" >> "data/siafe_sweep_full_$S.out" 2>&1 &
      say "relançou sweep $S (pid $!)"
      sleep 15
    fi
  done
  if done_sys 2 && done_sys 1; then
    say "AMBOS os sweeps concluídos"
    TOK=$(grep -m1 '^TELEGRAM_BOT_TOKEN=' /home/jfelippebethlem/.hermes/.env 2>/dev/null | cut -d= -f2- | tr -d '"'"'"' ')
    N=$(/home/jfelippebethlem/JFN/.venv/bin/python -c "import sqlite3;print(sqlite3.connect('/home/jfelippebethlem/JFN/data/compliance.db').execute('SELECT COUNT(*) FROM ob_orcamentaria_siafe').fetchone()[0])" 2>/dev/null)
    curl -s -F chat_id=45338178 -F text="✅ SWEEPS SIAFE 1 e 2 CONCLUÍDOS. Total de OBs na base: $N. Pronto p/ a análise pós-sweep e os TODOs (VACUUM, lock-por-sistema, dead-code)." "https://api.telegram.org/bot${TOK}/sendMessage" >/dev/null 2>&1
    break
  fi
  sleep 180
done
say "supervisor encerrado"
