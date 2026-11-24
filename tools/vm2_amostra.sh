#!/bin/bash
# AMOSTRA INDEPENDENTE na VM-2 (clone ~/JFN-worker) — 23/11/2026. Ver tools/vm2_conferencia.py (amostra_exportar/ler).
# Lê com o navegador DESTA máquina processos que o IT-CAMPO entregou (nunca os que a própria VM-2 produziu: a VM-1
# não os exporta para cá, e o `amostra_ler` recusa de novo) e devolve as leituras num lote `amostra`; a VM-1 só
# compara com o acervo. Antes isso custava 1,5–2,8 h/dia de Chromium na VM-1 (load 5–10).
# Forma da casa: single-pass com teto, nice/ionice, e a MESMA trava do navegador SEI do worker que as íntegras e a
# varredura geral usam (data/.vm2_sei.lock) — nunca dois navegadores SEI juntos nesta máquina. NUNCA toca no SIAFE.
# Pausar: touch ~/JFN-worker/data/.pause_vm2_amostra
set -u
W=/home/ubuntu/JFN-worker
cd "$W" || exit 1
export TZ=America/Sao_Paulo
export PYTHONPATH="$W"
export SEI_MAX_DOCS=6
PY="$W/.venv/bin/python"
LOG="$W/data/vm2_amostra.log"
MAX=${1:-4}
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

[ -f "$W/data/.pause_vm2_amostra" ] && { say "pausado (.pause_vm2_amostra) — pulei"; exit 0; }
exec 9>"$W/data/.vm2_sei.lock"
# espera até 20 min (a varredura geral segura a trava até 50 min e solta entre disparos); sem a trava, pula
flock -w 1200 9 || { say "navegador SEI do worker ocupado há 20 min — pula"; exit 0; }

FILA="$W/data/fila_amostra_vm2.json"
if ! ssh -o BatchMode=yes -o ConnectTimeout=20 vm1-ts \
     "cd /home/ubuntu/JFN && PYTHONPATH=. nice -n 10 timeout 120 .venv/bin/python -m tools.vm2_conferencia amostra-exportar --no $(hostname) --max $MAX" \
     > "$FILA.tmp" 2>>"$LOG"; then
  say "amostra-exportar na VM-1 falhou — fim"; exit 1
fi
mv "$FILA.tmp" "$FILA"
N=$("$PY" -c "import json,sys;print(len(json.load(open(sys.argv[1]))))" "$FILA")
say "VM-1 despachou $N processo(s) para leitura independente"
[ "$N" -gt 0 ] || exit 0
nice -n 10 ionice -c2 -n6 timeout -k 60 --foreground 2400 "$PY" -m tools.vm2_conferencia amostra-ler --fila "$FILA" >> "$LOG" 2>&1
say "amostra-ler rc=$? — fim"
