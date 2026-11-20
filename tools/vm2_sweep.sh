#!/bin/bash
# sweeps determinísticos da VM-2 — alívio de carga da VM-1 (pedido do dono, 2026-07-28).
#
# O QUE RODA AQUI, E POR QUÊ SÓ ISTO: as duas varreduras leem a produção em SÓ-LEITURA e
# escrevem em banco PRÓPRIO (data/achados.db). São CPU/IO, não rede — exatamente a carga que
# fazia a VM-1 competir consigo mesma.
#
# O QUE NUNCA PODE RODAR AQUI: qualquer coletor SIAFE. O SIAFE aceita UMA sessão por IP e a
# segunda DERRUBA a primeira. A trava está em compliance_agent/host_siafe.py e o marcador
# data/.siafe_host aponta para jfn-core — mas a primeira defesa é não chamar.
#
# Convive com o Massare: `nice`/`ionice` baixos e recuo quando a máquina está carregada. Os
# timers do dono (massare-market, descobre-doe, sei-pcrj) têm prioridade.
set -u
cd /home/ubuntu/JFN || exit 1
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/vm2_sweeps.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

[ -f data/.pause_vm2 ] && { say "pausado (.pause_vm2)"; exit 0; }
L=$(awk '{print int($1)}' /proc/loadavg)
[ "$L" -ge 3 ] && { say "load $L — cedendo a vez (Massare/timers do dono)"; exit 0; }

PRIO="nice -n 15 ionice -c3"
say "início"
$PRIO timeout -k 60 1500 $PY tools/varredura_certames_sweep.py \
      --com-clausulas --limite 300 --gravar >> data/vm2_certames.log 2>&1
say "certames rc=$?"
$PRIO timeout -k 60 1500 $PY tools/varredura_orgaos_sweep.py \
      --exercicio "$(date +%Y)" --limite-ugs 25 --max-fornecedores 12 --gravar \
      >> data/vm2_orgaos.log 2>&1
say "orgaos rc=$?"
say "fim"
