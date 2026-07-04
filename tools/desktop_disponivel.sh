#!/bin/bash
HB="$HOME/shared-brain/_handoff/orquestracao/it-campo-alive.txt"
[ -f "$HB" ] || exit 1
AGE=$(( $(date +%s) - $(stat -c %Y "$HB") ))
[ "$AGE" -lt 300 ] && exit 0 || exit 1
