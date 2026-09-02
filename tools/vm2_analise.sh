#!/usr/bin/env bash
# vm2_analise — a analise PESADA roda na VM-2, dentro do teto de 10 GB pedido pelo dono.
#
# O QUE VEM PARA CA e por que. Sao passadas de STREAMING sobre arquivos grandes, que na VM-1
# disputam os mesmos 2 vCPU da captura SEI e do painel:
#
#   · `agente_publico_reverso` — 27,6 milhoes de linhas do cadastro nacional de socios contra as
#     folhas conhecidas. 206 s de streaming puro, memoria baixa (nada e carregado inteiro).
#   · `grafo_persistir` — percorre credores do SIAFE montando cadeia societaria e contato
#     compartilhado. ~2 s por credor; sobram 4.765 dos 5.615.
#   · `elos_ocultos` e `cocontato_certame` — leem o que os dois acima produzem.
#
# O RESULTADO FICA NO BANCO DA VM-2 e e colhido pela VM-1 (`colher_vm2.sh`), do mesmo jeito que a
# arvore do SEI. Duas maquinas produzindo e uma analisando so funciona com a ponte — sem ela a
# segunda gasta CPU para ninguem, que foi o que aconteceu por dias com o sweep SEI.
#
# Cede a vez se a carga passar de 3: a CAPTURA tem prioridade, porque produz dado novo.
set -u
cd /home/ubuntu/JFN || exit 1
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/vm2_analise.log
say(){ echo "[$(date '+%F %T')] [vm2_analise] $*" | tee -a "$LOG"; }

[ -f data/.pause_vm2_analise ] && { say "pausada"; exit 0; }
L=$(awk '{print int($1)}' /proc/loadavg)
if [ "$L" -ge 3 ]; then say "load $L — cedendo a vez para a captura"; exit 0; fi
LIVRE=$(free -g | awk '/^Mem:/{print $7}')
if [ "${LIVRE:-0}" -lt 2 ]; then say "so ${LIVRE}GB livres — adiado"; exit 0; fi

PRIO="nice -n 15 ionice -c3"
say "inicio (load $L, ${LIVRE}GB livres)"
# LIMITE DIMENSIONADO PELO SLOT, não por gosto: ~1,9 s por credor MEDIDOS → 800 credores usam
# ~1.520 s dos 1.800 do timeout. Com 400, metade do slot ficava ociosa enquanto a cobertura do
# grafo estava em 9,4% do universo de credores (1.558 de 16.651 em 08/08) — e elo oculto só
# existe dentro do que o grafo percorreu.
$PRIO timeout -k 60 1800 $PY -m tools.grafo_persistir --limite 800 >> data/vm2_grafo.log 2>&1
say "grafo rc=$?"
$PRIO timeout -k 60 900 $PY -m tools.agente_publico_reverso >> data/vm2_agente.log 2>&1
say "agente publico rc=$?"
$PRIO timeout -k 60 600 $PY -m tools.elos_ocultos >> data/vm2_elos.log 2>&1
say "elos ocultos rc=$?"
$PRIO timeout -k 60 600 $PY -m tools.cocontato_certame >> data/vm2_cocontato.log 2>&1
say "cocontato rc=$?"
say "fim"
