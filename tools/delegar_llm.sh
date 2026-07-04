#!/bin/bash
FILA="$HOME/shared-brain/_handoff/fila-llm"
"$HOME/JFN/tools/desktop_disponivel.sh" || exit 2
ID="vm-$(date +%s)-$$"
printf '%s\n' "$1" > "$FILA/$ID.job.md"
for i in $(seq 1 150); do
  if [ -f "$FILA/$ID.done.md" ]; then cat "$FILA/$ID.done.md"; mv "$FILA/$ID.done.md" "$FILA/$ID.done.lido" 2>/dev/null; exit 0; fi
  sleep 2
done
exit 3
