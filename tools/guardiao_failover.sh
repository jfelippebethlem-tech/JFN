#!/bin/bash
LOG="$HOME/JFN/data/guardiao_failover.log"
if "$HOME/JFN/tools/desktop_disponivel.sh"; then
  echo "$(date -Is) desktop=ONLINE reforcando (LLM/analise no it-campo)" >> "$LOG"
else
  echo "$(date -Is) desktop=OFFLINE VM-assume-tudo (modelos IA proprios)" >> "$LOG"
fi
