#!/bin/bash
# Espera o navegador ficar livre e ENTÃO captura os processos da AMC.
#
# POR QUE EXISTE. A diligência da AMC (CNPJ 50917361000175) foi barrada QUATRO vezes seguidas: o
# `browser.lock` estava com sweeps de OUTRA SESSÃO (`sei_bombeiros_sweep`, `sei_sweep --ug 140100`),
# que rodam por cron e reaparecem. Tentar de rodada em rodada é gastar supervisão para acertar uma
# janela que dura minutos; este esperador acerta a janela sozinho.
#
# O QUE ESTÁ EM JOGO: R$ 41,59 mi pagos à AMC em processos que NÃO ESTÃO CAPTURADOS — o leitor duplo
# só lê o que já foi capturado, então a varredura jamais os alcançaria. Só o navegador chega lá.
#
# GUARDAS DA CASA, todas obrigatórias:
#   · NUNCA matar nem desabilitar processo/cron de outra sessão — só esperar;
#   · não somar navegador a navegador: 2 Chromium já derrubaram esta VM 4×;
#   · teto de carga antes de disparar (a leitura em 4 fatias já ocupa a máquina);
#   · janela de espera FINITA — sem `while true` eterno.
set -u
cd /home/ubuntu/JFN || exit 1

FIM=$(( $(date +%s) + 7200 ))          # desiste após 2 h em vez de virar processo eterno

while [ "$(date +%s)" -lt "$FIM" ]; do
  # `ps -C python` não enxerga shells, então este script não casa consigo mesmo — a armadilha do
  # `pgrep -f` que já mordeu esta casa (o waiter se via na própria lista e nunca liberava).
  alheios=$(ps -C python -o args= 2>/dev/null | grep -E 'sweep|recaptura' | grep -vc leitura_dupla)
  carga=$(awk '{printf "%d", $1}' /proc/loadavg)
  if [ "$alheios" -eq 0 ] && [ "$carga" -lt 3 ]; then
    echo "$(date -Is) navegador livre (carga $carga) — capturando AMC"
    set -a; . .env 2>/dev/null; set +a
    exec timeout 2400 nice -n 10 .venv/bin/python -m tools.sei_sweep \
        --cnpj 50917361000175 --max 8
  fi
  sleep 60
done
echo "$(date -Is) desisti após 2 h — navegador nunca ficou livre (alheios=$alheios carga=$carga)"
