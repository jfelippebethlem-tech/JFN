#!/bin/bash
# Detectores de padrões (tools.padroes_varrer) FORA da VM-1: sincroniza a réplica só-leitura no it-campo e roda lá
# os 25 em paralelo (deploy/itcampo/replica/). A VM-1 só serve páginas/arquivos pelo ssh com prioridade baixa e
# recebe os JSON de volta em data/padroes/. Sem it-campo (ssh falhou ou a rodada falhou) → o rodízio LOCAL de antes
# (45 min, saída mais velha primeiro), para nenhum detector ficar sem rodar. Chamado pela propagação (config/propagacao.yaml).
set -u
J=/home/ubuntu/JFN
cd "$J" || exit 1
S=(ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=60 it-campo 'wsl -d Ubuntu -- bash -s')
echo "[$(date '+%F %T')] réplica → it-campo"
if timeout -k 60 2400 "${S[@]}" < deploy/itcampo/replica/replica_sync.sh \
   && timeout -k 60 2700 "${S[@]}" -- "${JFN_PADROES_PARALELO:-4}" < deploy/itcampo/replica/padroes_remoto.sh; then
  echo "[$(date '+%F %T')] it-campo ok"
  exit 0
fi
# O derivado está como "leve" na propagação (o trabalho é do it-campo); o rodízio local é pesado: só com a VM folgada.
L=$(cut -d' ' -f1 /proc/loadavg)
if awk -v l="$L" 'BEGIN{exit !(l > 7)}'; then
  echo "[$(date '+%F %T')] it-campo falhou e a VM-1 está em carga $L — adiado (a propagação tenta de novo)"
  exit 75
fi
echo "[$(date '+%F %T')] it-campo indisponível ou falhou — rodízio local"
exec nice -n 15 .venv/bin/python -m tools.padroes_varrer --orcamento-s 2700
