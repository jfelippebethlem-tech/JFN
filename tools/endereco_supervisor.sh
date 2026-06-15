#!/bin/bash
# endereco_supervisor — mantém a VERIFICAÇÃO DE ENDEREÇO de TODOS os fornecedores VIVA e detached
# (igual sei_supervisor/siafe_supervisor): roda em lotes educados até a fila de sedes não-verificadas
# esvaziar; quando esvazia, faz back-off longo e reavalia (o cache expira em 7d e novos fornecedores
# surgem com o SIAFE). Resumível por construção (o backfill pega sempre os ainda-sem-verificação).
#
# Detached/persistente: lançado pelo cron-minuto (respawn) + @reboot, nunca preso à sessão do Claude.
# VM-safe: respeita load (não derruba a VM); a fonte OSM (Nominatim/Overpass) tem back-off próprio.
# Pausa manual: criar data/.pause_endereco_sweep (encerra limpo e o supervisor aguarda).
cd /home/ubuntu/JFN || exit 1
LOG=data/endereco_supervisor.log
LOTE="${ENDERECO_LOTE:-800}"
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

say "endereco_supervisor iniciado (lote=$LOTE${SWEEP_MAX_SECONDS:+, sessão diária ${SWEEP_MAX_SECONDS}s})"
while true; do
  # sessão diária limitada (cron escalonado): encerra após SWEEP_MAX_SECONDS p/ não sobrepor o próximo sweep
  # (VM-safe — §8). Sem a var = contínuo (retrocompatível). Resumível: o próximo dia continua de onde parou.
  if [ "${SWEEP_MAX_SECONDS:-0}" -gt 0 ] && [ "$SECONDS" -ge "${SWEEP_MAX_SECONDS}" ]; then
    say "sessão diária atingiu ${SWEEP_MAX_SECONDS}s — encerrando (resumível amanhã)"; exit 0; fi
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
