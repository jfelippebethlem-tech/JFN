#!/bin/bash
# Lane do ARQUIVAMENTO — transforma cache de captura em arquivo legível.
#
# POR QUE ESTE ARQUIVO EXISTE. O pipeline tem três estágios e só dois estavam no cron:
#   sei_sweep (*/30) -> data/sei_cache/cdp_*.json -> [NADA] -> data/sei_arquivo/ -> varredura (*/10)
# O estágio do meio, `sei_arquivar_do_cache`, dependia de eu lembrar de rodá-lo à mão. Medido em
# 2026-08-15: 7 processos com texto no cache e SEM arquivo, 2.827.369 caracteres — entre eles o
# `080002/016951/2024`, que tinha sido LIDO com 2.824 chars enquanto 742.485 esperavam no cache
# (0,4% do texto). A leitura não estava errada; ela estava lendo um arquivo pela metade.
#
# CAPTURAR NÃO É TORNAR LEGÍVEL. Nada nisso vira erro em log: a cobertura marca 100%, porque o
# processo TEM arquivo — só não tem o arquivo inteiro. Este lane fecha o vão.
#
# FORMA OBRIGATÓRIA DA CASA (aprendizados/obediencia-e-loop-autonomo):
#   · single-pass com `timeout`, NUNCA `while true`;
#   · `flock` para não somar duas cópias;
#   · guarda de memória (vetor real das quedas desta VM) antes de entrar;
#   · kill-switch por arquivo, sem precisar mexer no cron.
#
# Desligar:  touch data/.arquivar_cache.off
# Religar :  rm -f data/.arquivar_cache.off
set -u
cd /home/ubuntu/JFN || exit 1

[ -f data/.arquivar_cache.off ] && exit 0

exec 9>/tmp/arquivar_cache.lock
flock -n 9 || exit 0

# `ps -C python` não enxerga shells, então este script não casa consigo mesmo — a armadilha do
# `pgrep -f` que já mordeu esta casa.
if ps -C python -o args= 2>/dev/null | grep -q "sei_arquivar_do_cache"; then
  exit 0
fi

livre_mb=$(awk '/MemAvailable/{printf "%d", $2/1024}' /proc/meminfo)
[ "$livre_mb" -lt 1500 ] && exit 0
carga=$(awk '{printf "%d", $1}' /proc/loadavg)
[ "$carga" -ge 6 ] && exit 0

# Este lane LÊ JSON grande e ESCREVE arquivo — ao contrário da varredura (que espera rede), ele
# queima CPU e disco de verdade. Por isso o teto aqui é 6, e não o 12 da varredura.
set -a; . .env 2>/dev/null; set +a
timeout 1500 nice -n 10 ionice -c3 .venv/bin/python -m tools.sei_arquivar_do_cache \
    --max 60 --aplicar >> data/arquivar_cache.log 2>&1 9>&-

echo "$(date -Is) disparo encerrado (saída $?)" >> data/arquivar_cache.log
