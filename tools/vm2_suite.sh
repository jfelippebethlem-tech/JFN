#!/usr/bin/env bash
# vm2_suite — a SUÍTE roda na VM-2, e o resultado volta como DELTA, não como "verde absoluto".
#
# POR QUE ISTO EXISTE. A VM-1 gasta de 2 a 18 minutos POR LOTE rodando a suíte, disputando 2 vCPU
# com a captura SEI, o sweep de dados e o painel — medido nesta sessão: o lote 4 levou 1 minuto numa
# rodada e 18 na seguinte, só por contenção. A VM-2 roda os mesmos quatro lotes em ~15 minutos com
# pico de 8 GB de 11, porque está ociosa a maior parte do dia.
#
# O RESULTADO É COMPARADO NOME A NOME, nunca por contagem. `tests/BASE-FALHAS-VM2.txt` registra as
# falhas de AMBIENTE dessa máquina (base de dados diferente, sem o acervo completo) — exigir zero
# ali transformaria o gate em alarme permanente, e alarme permanente é alarme desligado. O que
# interessa é a falha NOVA: `ci_delta` sai com 1 só quando aparece nome que não estava na base.
#
# Convive com o resto: `nice`/`ionice` no fundo, e cede a vez se a máquina estiver carregada — a
# captura SEI da fatia 1/2 e o sweep SEI-PCRJ têm prioridade, porque produzem dado novo e a suíte
# só confere o que já existe.
set -u
cd /home/ubuntu/JFN || exit 1
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/vm2_suite.log
say(){ echo "[$(date '+%F %T')] [vm2_suite] $*" | tee -a "$LOG"; }

[ -f data/.pause_vm2_suite ] && { say "pausada (.pause_vm2_suite)"; exit 0; }
L=$(awk '{print int($1)}' /proc/loadavg)
if [ "$L" -ge 3 ]; then say "load $L — cedendo a vez para a captura"; exit 0; fi

PRIO="nice -n 15 ionice -c3"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
say "início (load $L)"
for l in 1 2 3 4; do
  $PRIO timeout -k 60 1800 $PY -m pytest -q -rf -p no:randomly \
        $($PY -m tools.ci_lote "$l" 4) >> "$TMP/lote.log" 2>&1
  say "lote $l rc=$? — $(tail -1 "$TMP/lote.log" | tr -d '\r')"
done

# DELTA, não verde: falha nova é regressão; falha conhecida é ambiente.
$PY -m tools.ci_delta "$TMP/lote.log" --base tests/BASE-FALHAS-VM2.txt >> "$LOG" 2>&1
rc=$?
if [ "$rc" -ne 0 ]; then
  say "REGRESSÃO — falha NOVA (não está na base de ambiente). Ver $LOG"
else
  say "delta zero — nenhuma falha nova"
fi
exit 0
