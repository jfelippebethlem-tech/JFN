#!/bin/bash
# endereco_supervisor — mantém a VERIFICAÇÃO DE ENDEREÇO de TODOS os fornecedores VIVA e detached
# (igual sei_supervisor/siafe_supervisor): roda em lotes educados até a fila de sedes não-verificadas
# esvaziar; quando esvazia, faz back-off longo e reavalia (o cache expira em 7d e novos fornecedores
# surgem com o SIAFE). Resumível por construção (o backfill pega sempre os ainda-sem-verificação).
#
# Detached/persistente: lançado pelo cron-minuto (respawn) + @reboot, nunca preso à sessão do Claude.
# VM-safe: respeita load (não derruba a VM); a fonte OSM (Nominatim/Overpass) tem back-off próprio.
# Pausa manual: criar data/.pause_endereco_sweep (encerra limpo e o supervisor aguarda).
cd /home/jfelippebethlem/JFN || exit 1
LOG=data/endereco_supervisor.log
LOTE="${ENDERECO_LOTE:-800}"
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

say "endereco_supervisor iniciado (lote=$LOTE)"
while true; do
  if [ -f data/.pause_endereco_sweep ]; then sleep 120; continue; fi
  # já rodando um lote (ex.: lançado à mão)? não duplica (evita 2 clientes na mesma fonte OSM)
  if pgrep -f "tools.backfill_verificacao_endereco" >/dev/null; then sleep 60; continue; fi
  # respeita CPU: load alto → espera (a VM já caiu por excesso; nunca forçar)
  L=$(awk '{print int($1)}' /proc/loadavg)
  if [ "$L" -ge 3 ]; then say "load $L alto — espera 120s"; sleep 120; continue; fi
  OUT=$(PYTHONPATH=. .venv/bin/python -m tools.backfill_verificacao_endereco --limite "$LOTE" --pausa 0.4 2>&1)
  echo "$OUT" | tail -1 >> "$LOG"
  if echo "$OUT" | grep -q "^\[backfill_verif_end\] 0 fornecedor"; then
    # fila vazia → todas as sedes conhecidas já verificadas; back-off longo e reavalia (cache 7d / novos CNPJs)
    say "fila vazia — todas as sedes verificadas; back-off 6h e reavalia"; sleep 21600
  else
    sleep 15
  fi
done
