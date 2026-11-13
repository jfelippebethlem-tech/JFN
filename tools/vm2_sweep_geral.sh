#!/bin/bash
# Varredura GERAL do SEI na VM-2 (clone ~/JFN-worker), fatia 1/2, entregue à VM-1 por lote CONFERIDO.
# Ver tools/vm2_sweep_geral.py. Agendado por deploy/vm2/jfn-sweep-geral-vm2.timer (a cada 30 min).
# Single-pass com teto; trava COMPARTILHADA com as íntegras (um navegador SEI do worker por vez).
# NUNCA toca no SIAFE (data/.siafe_host=jfn-core no worker).
set -u
W=/home/ubuntu/JFN-worker
cd "$W" || exit 1
export TZ=America/Sao_Paulo
export PYTHONPATH="$W"
export JFN_SWEEP_FATIA=1/2
export JFN_CLAUDE_BIN="${JFN_CLAUDE_BIN:-/home/ubuntu/.local/bin/claude}"
export JFN_CLAUDE_MAX_CHAMADAS_DIA="${JFN_CLAUDE_MAX_CHAMADAS_DIA:-60}"
export JFN_CLAUDE_MAX_CONFERENCIA_VM2="${JFN_CLAUDE_MAX_CONFERENCIA_VM2:-40}"
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
PY="$W/.venv/bin/python"
LOG="$W/data/vm2_sweep_geral.log"
MAX=${1:-8}
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

exec 9>"$W/data/.vm2_sei.lock"
flock -n 9 || { say "íntegras/varredura já com o navegador — pula"; exit 0; }
[ -f "$W/data/.pause_vm2_sweep" ] && { say "pausado (.pause_vm2_sweep) — pulei"; exit 0; }
git -C "$W" pull --ff-only -q 2>>"$LOG" || say "git pull falhou — seguindo com $(git -C "$W" rev-parse --short HEAD)"

SSH="ssh -o BatchMode=yes -o ConnectTimeout=20 vm1-ts"
# 1) fila da VM-1 (fatia 1/2): renovada a cada 6 h — o _fila consulta o banco de 5 GB da VM-1
if [ -z "$(find "$W/data/fila_sweep_vm2.json" -mmin -360 2>/dev/null)" ]; then
  if $SSH "cd /home/ubuntu/JFN && PYTHONPATH=. nice -n 10 timeout 900 .venv/bin/python -m tools.vm2_sweep_geral exportar --max 300" \
       > "$W/data/fila_sweep_vm2.json.tmp" 2>>"$LOG"; then
    mv "$W/data/fila_sweep_vm2.json.tmp" "$W/data/fila_sweep_vm2.json"
    say "fila exportada pela VM-1: $("$PY" -c 'import json,sys;print(len(json.load(open(sys.argv[1]))))' "$W/data/fila_sweep_vm2.json") processos"
  else
    say "exportar na VM-1 falhou — sigo com a fila anterior, se houver"
  fi
fi
[ -s "$W/data/fila_sweep_vm2.json" ] || { say "sem fila — fim"; exit 0; }

# 2) o estado de decisão da VM-1 (progresso e restritos), para o _pular decidir igual; e a foto do "antes"
mkdir -p "$W/data/sei_cache"
rsync -a vm1-ts:/home/ubuntu/JFN/data/sei_cache/sei_sweep_progress.json "$W/data/sei_cache/sei_sweep_progress.json" 2>>"$LOG" \
  && rsync -a vm1-ts:/home/ubuntu/JFN/data/sei_restritos.json "$W/data/sei_restritos.json" 2>>"$LOG" \
  || { say "não consegui copiar o progresso da VM-1 — sem ele o _pular releria o já lido; fim"; exit 1; }
cp "$W/data/sei_cache/sei_sweep_progress.json" "$W/data/.vm2_prog_antes.json"
cp "$W/data/sei_restritos.json" "$W/data/.vm2_restritos_antes.json"

# 3) o lote (sweep canônico, fila injetada)
DESDE=$(date +%s)
nice -n 10 ionice -c2 -n6 timeout -k 120 --foreground 1500 "$PY" -m tools.vm2_sweep_geral rodar --max "$MAX" >> "$LOG" 2>&1
say "rodar rc=$?"

# 4) lote conferido para a VM-1
"$PY" -m tools.vm2_sweep_geral devolver --desde "$DESDE" >> "$LOG" 2>&1
say "devolver rc=$? — fim"
