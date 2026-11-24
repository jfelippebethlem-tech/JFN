#!/usr/bin/env bash
# Semáforo ÚNICO de trabalho pesado da VM-1 (23/11/2026 — plano de reescrita, Fase 0c).
# Achado: 5 pesados ao mesmo tempo com swap 100% (sei_depurar_pdfs, vinculo_ob_contrato, sei_compactar, tesseract,
# leitura dupla). O despachante de propagação (compliance_agent/propagacao.py::_semaforo_pesado) divide esta MESMA
# trava: um pesado por vez na VM inteira, seja cron, seja derivado.
#
# Uso (crontab):  tools/pesado.sh <nome> <espera_max_s> <comando...>
#   espera a trava até <espera_max_s>; depois espera carga ≤ PESADO_CARGA_MAX (6) no tempo que sobrar;
#   não conseguiu → registra "adiado" e sai 0 (o próximo horário tenta de novo; o SLO acusa se nunca rodar).
#   Roda com nice 15 + ionice idle e SEGURA a trava até o comando terminar.
set -u
nome=${1:?nome}; espera=${2:?espera_max_s}; shift 2
cd /home/ubuntu/JFN || exit 1
mkdir -p data/locks
carga_max=${PESADO_CARGA_MAX:-6}
log() { echo "$(date '+%F %T') [pesado:$nome] $*" >> data/pesado_vm1.log; }
ini=$(date +%s)
exec 8>data/locks/pesado_vm1.lock
if ! flock -w "$espera" 8; then
  log "adiado: semáforo ocupado por ${espera}s"; exit 0
fi
# 24/11/2026: derivado do grafo de propagação ATRASADO pediu a vez (compliance_agent/propagacao.py::_pedir_vez_pesado).
# Sem isto o sei_compactar (de hora em hora, ~55 min) emendava uma rodada na outra e o despachante, que só tenta
# sem esperar, nunca pegava a trava (pesados do grafo parados 20–45 h). Pedido fresco = devolve a trava e sai.
pedido=data/locks/pesado_vm1.pedido
validade=${PESADO_PEDIDO_VALIDADE_S:-900}
if [ -f "$pedido" ] && [ $(( $(date +%s) - $(stat -c %Y "$pedido") )) -lt "$validade" ]; then
  log "adiado: vez pedida pelo despachante ($(head -c 120 "$pedido"))"; exit 0
fi
while ! awk -v l="$(cut -d' ' -f1 /proc/loadavg)" -v m="$carga_max" 'BEGIN{exit !(l <= m)}'; do
  if [ $(( $(date +%s) - ini )) -ge "$espera" ]; then
    log "adiado: carga $(cut -d' ' -f1 /proc/loadavg) > $carga_max"; exit 0
  fi
  sleep 30
done
log "início (esperou $(( $(date +%s) - ini ))s)"
nice -n 15 ionice -c3 "$@"
rc=$?
log "fim rc=$rc ($(( $(date +%s) - ini ))s)"
exit $rc
