#!/bin/bash
# ONLINE se o heartbeat MUDOU nos últimos 300s (medido pelo relógio da VM, imune ao clock do desktop).
HB="$HOME/shared-brain/_handoff/orquestracao/it-campo-alive.txt"
ST="$HOME/JFN/data/.desktop_hb_state"
[ -f "$HB" ] || exit 1
NOW=$(date +%s)
CUR=$(stat -c %Y "$HB")
if [ -f "$ST" ]; then read -r LAST_MT LAST_CHG < "$ST"; else LAST_MT=""; LAST_CHG=$NOW; fi
if [ "$CUR" != "$LAST_MT" ]; then          # heartbeat avançou → vivo; registra o momento (relógio VM)
  echo "$CUR $NOW" > "$ST"; exit 0
fi
[ $(( NOW - LAST_CHG )) -lt 300 ] && exit 0 || exit 1   # sem mudança há <300s = ok; senão offline
