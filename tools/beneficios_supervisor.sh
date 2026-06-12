#!/bin/bash
# beneficios_supervisor — mantém o SWEEP DE BENEFÍCIOS DOS SÓCIOS (laranja) vivo e detached
# (igual sei_/endereco_/siafe_supervisor): roda lotes educados até a fila de sócios não-processados
# (socios_fornecedor mascarados ainda não em socio_beneficio) esvaziar; quando esvazia, back-off longo
# e reavalia (novos sócios entram com a ingestão de QSA; a cobertura de CPF cresce com TSE/favorecidos).
# Resumível por construção (o sweep pega sempre os AINDA-sem-registro).
#
# Detached/persistente: lançado pelo cron-minuto (respawn) + @reboot, nunca preso à sessão do Claude.
# ⚠ LIÇÃO §8 (self-match): o pgrep do CRON deve usar BRACKET p/ não casar o próprio sh do cron —
#   a linha do crontab é  * * * * * pgrep -f 'beneficios_superviso[r].sh' >/dev/null || nohup .../beneficios_supervisor.sh &
# VM-safe: respeita load (não derruba a VM). O Portal tem rate-limit → --pausa entre CPFs resolvidos.
# Pausa manual: criar data/.pause_beneficios_sweep (encerra limpo e o supervisor aguarda).
cd /home/jfelippebethlem/JFN || exit 1
LOG=data/beneficios_supervisor.log
LOTE="${BENEFICIOS_LOTE:-800}"
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

say "beneficios_supervisor iniciado (lote=$LOTE)"
while true; do
  if [ -f data/.pause_beneficios_sweep ]; then sleep 120; continue; fi
  # já rodando um lote (ex.: lançado à mão)? não duplica (evita 2 clientes no Portal). Bracket evita self-match.
  if pgrep -f "tools.beneficios_swee[p]" >/dev/null; then sleep 60; continue; fi
  # respeita CPU: load alto → espera (a VM já caiu por excesso; nunca forçar — §8)
  L=$(awk '{print int($1)}' /proc/loadavg)
  if [ "$L" -ge 3 ]; then say "load $L alto — espera 120s"; sleep 120; continue; fi
  OUT=$(PYTHONPATH=. .venv/bin/python -m tools.beneficios_sweep --limite "$LOTE" --pausa 0.3 2>&1)
  echo "$OUT" | tail -1 >> "$LOG"
  if echo "$OUT" | grep -q "^\[beneficios_sweep\] 0 socios"; then
    # fila vazia → todos os sócios conhecidos já processados; back-off longo e reavalia
    say "fila vazia — todos os sócios processados; back-off 6h e reavalia"; sleep 21600
  else
    sleep 15
  fi
done
