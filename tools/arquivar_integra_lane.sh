#!/bin/bash
# Lane do arquivamento da ÍNTEGRA (PDF) — o irmão do arquivar_cache_lane.sh, para a OUTRA via.
#
# POR QUE ESTE ARQUIVO EXISTE. O acervo SEI chega por DUAS vias, e só uma tinha lane:
#   via cdp     : sei_sweep (*/30) -> sei_cache/cdp_*.json  -> arquivar_cache_lane.sh (*/20) -> OK
#   via íntegra : sei_integra_fila.py (04:00) -> sei_cache/integra_*/NNN.pdf -> [NADA] -> parado
# O produtor da íntegra TEM cron desde sempre; o consumidor (`sei_arquivar.py --pendentes`) só era
# chamado pelo `bombeiros_supervisor.sh` — o supervisor dos BOMBEIROS. O docstring da função diz
# "Para o supervisor do sweep", mas o supervisor geral do sweep está DEPRECADO e o cron que o
# substituiu (`sweep_sei.sh`) não a chama. Ninguém percebeu porque o fluxo dos bombeiros funcionava.
#
# MEDIDO EM 2026-08-22, antes de existir este lane: 4 processos com PDF baixado e não arquivado —
# 1.381 PDFs, 0,93 GB. DOIS deles com o manifesto declarando `captura_vazia: True` enquanto 40 e
# 319 PDFs, com texto extraível, esperavam no cache. O `080002/019206/2025` tinha PDFs de 18/08 e
# manifesto de 21/07: o arquivamento rodou quando o cache estava vazio e nunca mais voltou.
#
# CAPTURAR NÃO É TORNAR LEGÍVEL — e aqui a mentira é pior que no irmão: o manifesto AFIRMA
# "captura vazia" sobre um cache cheio. A leitura seguinte lê zero e conclui lacuna do processo.
#
# `arquivar_pendentes()` já resolve o frescor sozinha: pula quando o manifesto é mais novo que
# TODO o cache, e re-arquiva quando não é. Este lane só lhe dá horário e guardas.
#
# FORMA OBRIGATÓRIA DA CASA (aprendizados/obediencia-e-loop-autonomo):
#   · single-pass com `timeout`, NUNCA `while true`;
#   · `flock` para não somar duas cópias;
#   · guarda de MEMÓRIA — vetor real das quedas desta VM, não a carga;
#   · cede a vez à CAPTURA: ordem por escassez é captura > arquivamento > varredura, nunca junto;
#   · kill-switch por arquivo, sem mexer no cron.
#
# O OCR fica LIGADO de propósito: o PDF do SEI é frequentemente imagem, e sem OCR o arquivo sai
# vazio de novo — que é exatamente o defeito que este lane existe para fechar. Por isso ele roda
# de madrugada, com nice/ionice, e cede a vez a qualquer captura em voo.
#
# Desligar:  touch data/.arquivar_integra.off
# Religar :  rm -f data/.arquivar_integra.off
set -u
cd /home/ubuntu/JFN || exit 1

[ -f data/.arquivar_integra.off ] && exit 0

exec 9>/tmp/arquivar_integra.lock
flock -n 9 || exit 0

# `ps -C python` (nunca `pgrep -f`, que casa a si mesmo).
if ps -C python -o args= 2>/dev/null | grep -qE "sei_arquivar\.py"; then exit 0; fi

# CEDER À CAPTURA, MAS COM COTA CONTRA INANIÇÃO.
#
# A primeira versão cedia SEMPRE que houvesse captura em voo. Medido em 2026-08-23, o cron disparou
# às 00:10, 03:10 e 06:10 e o lane saiu nas TRÊS — o `sweep_sei` roda de 30 em 30 min e seus ciclos
# se emendam ("ciclo anterior ainda rodando — pula"), então a janela livre quase não existe e o
# arquivamento morreria de fome. É a lição `siafe-dreno-cota-contra-inanicao` de novo:
# PRIORIDADE ESTRITA COM VAZÃO BAIXA É EXCLUSÃO, não prioridade.
#
# Regra: cede enquanto a última execução REAL for recente; passado o teto, roda junto — protegido
# por `nice`/`ionice`, que é o que torna a convivência possível sem tirar a vez da captura.
TETO_JEJUM_H=${ARQUIVA_INTEGRA_JEJUM_H:-12}
ultima=0
[ -f data/.arquivar_integra.ultima ] && ultima=$(cat data/.arquivar_integra.ultima 2>/dev/null || echo 0)
jejum_h=$(( ($(date +%s) - ultima) / 3600 ))

if ps -C python -o args= 2>/dev/null | grep -qE "tools\.sei_sweep|sei_integra_fila"; then
  if [ "$jejum_h" -lt "$TETO_JEJUM_H" ]; then
    # SILÊNCIO NÃO É SUCESSO — e também não é falha. A cessão vai para o log, senão a próxima
    # investigação vê log vazio e não sabe se o cron falhou ou se o script cedeu de propósito.
    echo "$(date -Is) cedi à captura (jejum ${jejum_h}h < ${TETO_JEJUM_H}h)" >> data/arquivar_integra.log
    exit 0
  fi
  echo "$(date -Is) captura em voo, mas jejum ${jejum_h}h >= ${TETO_JEJUM_H}h — rodando junto (nice/ionice)" >> data/arquivar_integra.log
fi

livre_mb=$(awk '/MemAvailable/{printf "%d", $2/1024}' /proc/meminfo)
[ "$livre_mb" -lt 1500 ] && exit 0

carga=$(awk '{printf "%d", $1}' /proc/loadavg)
[ "$carga" -ge 6 ] && exit 0

set -a; . .env 2>/dev/null; set +a

timeout 1500 nice -n 10 ionice -c3 .venv/bin/python tools/sei_arquivar.py --pendentes \
    >> data/arquivar_integra.log 2>&1 9>&-
rc=$?
# Marca a execução REAL (não a cessão): é o relógio do jejum acima.
date +%s > data/.arquivar_integra.ultima
echo "$(date -Is) disparo encerrado (saída $rc)" >> data/arquivar_integra.log
