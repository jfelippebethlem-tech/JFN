#!/bin/bash
# endereco_catchup — varre o endereço de TODOS os fornecedores ainda não verificados, em lotes
# educados (Nominatim/Overpass com back-off), até a fila esvaziar. VM-safe: respeita load. Resumível
# (cada lote pega os ainda-sem-verificação). Pausa manual: data/.pause_endereco_catchup. Não é cron eterno:
# encerra sozinho quando "0 fornecedor(es) a verificar".
cd /home/jfelippebethlem/JFN || exit 1
LOG=data/endereco_catchup.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
say "catchup iniciado"
while true; do
  [ -f data/.pause_endereco_catchup ] && { say "pausado"; sleep 120; continue; }
  # respeita CPU (não derruba a VM): espera se load alto
  L=$(awk '{print int($1)}' /proc/loadavg)
  if [ "$L" -ge 3 ]; then say "load $L alto — espera 120s"; sleep 120; continue; fi
  OUT=$(PYTHONPATH=. .venv/bin/python -m tools.backfill_verificacao_endereco --limite 800 --pausa 0.4 2>&1)
  echo "$OUT" | tail -2 >> "$LOG"
  if echo "$OUT" | grep -q "^\[backfill_verif_end\] 0 fornecedor"; then
    say "FILA VAZIA — todos os fornecedores verificados. encerrando."; break
  fi
  sleep 10
done
say "catchup encerrado"
