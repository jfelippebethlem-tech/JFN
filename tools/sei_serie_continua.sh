#!/bin/bash
# Guard de OOM: este sweep morre ANTES da sessão do dono (ver tools/lib/oom_guard.sh).
source "$(dirname "$0")/lib/oom_guard.sh" 2>/dev/null || true
#
# sei_serie_continua — análise processo a processo, em série, até acabar o acervo.
#
# POR QUE UM ENVELOPE E NÃO UM `--n 2000` DIRETO. São 2.049 processos restantes, cada um com
# leitura por IA: horas de execução. Uma única chamada longa morre por qualquer motivo (cota,
# provedor fora do ar, reinício da VM) e leva junto o que não foi gravado. Este laço roda em
# LOTES pequenos, e cada lote grava no índice antes do próximo começar — o progresso nunca
# depende de a execução inteira terminar.
#
# COMO PARAR (sem deploy, sem matar processo):
#   touch data/.pause_serie          # para no fim do lote corrente
#   touch data/.pause_sweeps         # para TODOS os sweeps da casa
#
# BOUNDED por natureza: `timeout` por lote, `nice`/`ionice` baixos, guard de OOM no topo, e
# recuo quando a VM está carregada. A VM tem 2 vCPU — um pesado por vez, sempre.
set -u
cd /home/ubuntu/JFN || exit 1
[ -f .env ] && { set -a; . ./.env; set +a; }
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/serie_continua.log
LOTE="${1:-8}"          # processos por lote
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

say "início · lote=$LOTE"
while :; do
    [ -f data/.pause_serie ] && { say "pausado (.pause_serie)"; break; }
    [ -f data/.pause_sweeps ] && { say "pausado (.pause_sweeps)"; break; }

    # Backstop de VM: com a máquina carregada, espera. O acervo não vai a lugar nenhum.
    L=$(awk '{print int($1)}' /proc/loadavg)
    if [ "$L" -ge 5 ]; then say "load $L alto — aguardando 5min"; sleep 300; continue; fi

    ANTES=$($PY -c "import json,pathlib;print(len(json.loads(pathlib.Path('data/analise_serie.json').read_text())))" 2>/dev/null || echo 0)
    nice -n 12 ionice -c2 -n7 timeout -k 60 3600 \
        $PY -u tools/sei_analise_em_serie.py --n "$LOTE" >> data/analise_serie_saida.log 2>&1
    rc=$?
    DEPOIS=$($PY -c "import json,pathlib;print(len(json.loads(pathlib.Path('data/analise_serie.json').read_text())))" 2>/dev/null || echo 0)
    say "lote rc=$rc · índice ${ANTES} -> ${DEPOIS}"

    # Nada avançou: ou acabou a fila, ou algo está travando. Nos dois casos, parar é o certo —
    # um laço que não progride só queima cota.
    if [ "$DEPOIS" = "$ANTES" ]; then
        say "sem progresso no lote — encerrando (fila esgotada ou bloqueio)"
        break
    fi
    sleep 20        # respiro entre lotes: a cota dos modelos :free é por janela de tempo
done
say "fim · índice final: $($PY -c "import json,pathlib;print(len(json.loads(pathlib.Path('data/analise_serie.json').read_text())))" 2>/dev/null || echo '?')"
