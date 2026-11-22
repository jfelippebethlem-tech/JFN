#!/bin/bash
# Laudos sem conclusão (compliance_agent.indeterminados) com a LEITURA DOS AUTOS fora da VM-1: sincroniza a réplica
# só-leitura no it-campo, diagnostica lá (sem teto de leitura) e traz o JSON com md5 conferido; aqui o ciclo só usa
# esse diagnóstico se a amostra re-diagnosticada na VM-1 der igual campo a campo (importar_diagnostico) — a escrita
# (fila SEI, fontes externas, estado) continua só na VM-1. Sem it-campo, ou rejeitado → o ciclo local de antes.
# Chamado pela propagação (config/propagacao.yaml, derivado `indeterminados`).
set -u
J=/home/ubuntu/JFN
cd "$J" || exit 1
S=(ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=60 it-campo 'wsl -d Ubuntu -- bash -s')
D=data/indeterminados/itcampo_diagnostico.json
ARGS=(ciclo --max-ler 150 --max-externo 300)
echo "[$(date '+%F %T')] réplica → it-campo"
rm -f "$D"
if timeout -k 60 2400 "${S[@]}" < deploy/itcampo/replica/replica_sync.sh \
   && timeout -k 60 3600 "${S[@]}" < deploy/itcampo/replica/indeterminados_remoto.sh && [ -s "$D" ]; then
  echo "[$(date '+%F %T')] it-campo ok — conferência por amostra e ciclo local"
  exec nice -n 10 .venv/bin/python -m compliance_agent.indeterminados "${ARGS[@]}" --diagnostico-de "$D"
fi
echo "[$(date '+%F %T')] it-campo indisponível ou falhou — ciclo local"
exec nice -n 10 .venv/bin/python -m compliance_agent.indeterminados "${ARGS[@]}"
