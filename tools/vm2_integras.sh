#!/bin/bash
# Rodada de ÍNTEGRAS do SEI na VM-2 (clone git ~/JFN-worker). Ver tools/sei_integra_vm2.py para o desenho.
#   uso: tools/vm2_integras.sh <segundos de orçamento> [max processos exportados]
# Agendado por deploy/vm2/jfn-integras-vm2.timer (madrugada e janela diurna, horário de Brasília).
#
# Forma da casa: single-pass com teto (`timeout -k --foreground`, nunca `while true`), flock contra cópia
# dupla, nice/ionice, UM navegador SEI por vez nesta máquina (pausa o sweep da cópia antiga ~/JFN e espera o
# ciclo dele soltar o browser; despausa no fim). NUNCA toca no SIAFE (sessão única por IP).
set -u
W=/home/ubuntu/JFN-worker
ANTIGO=/home/ubuntu/JFN              # cópia rsync antiga da VM-2, onde mora o jfn-sei-sweep (fatia 1/2)
export TZ=America/Sao_Paulo          # o log vai para a VM-1, que está em -03: as horas têm de casar
# orçamento: madrugada (antes das 08h) 5 h; janela diurna 3 h — ou o 1º argumento, se dado
if [ "$(date +%-H)" -lt 8 ]; then SEG=${1:-18000}; else SEG=${1:-10800}; fi
MAX=${2:-400}
cd "$W" || exit 1
export PYTHONPATH="$W"
PY="$W/.venv/bin/python"
LOG="$W/data/vm2_integras.log"
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

exec 9>"$W/data/.vm2_integras.lock"
flock -n 9 || { say "rodada anterior ainda viva — pula"; exit 0; }
[ -f "$W/data/.pause_vm2_integras" ] && { say "pausado (.pause_vm2_integras) — pulei"; exit 0; }

# código atual da VM-1 (fast-forward; se falhar, roda com o que tem e registra)
git -C "$W" pull --ff-only -q 2>>"$LOG" || say "git pull falhou — seguindo com $(git -C "$W" rev-parse --short HEAD)"

# 1) a VM-1 monta a fila (mesmo critério do código de lá) e grava a reserva
FILA="$W/data/fila_vm2.json"
if ! ssh -o BatchMode=yes -o ConnectTimeout=20 vm1-ts \
     "cd /home/ubuntu/JFN && PYTHONPATH=. nice -n 10 .venv/bin/python -m tools.sei_integra_vm2 exportar --max $MAX" \
     > "$FILA.tmp" 2>>"$LOG"; then
  say "exportar na VM-1 falhou — sem fila, sem rodada"; exit 1
fi
mv "$FILA.tmp" "$FILA"
N=$("$PY" -c "import json,sys;print(len(json.load(open(sys.argv[1]))))" "$FILA")
say "fila exportada pela VM-1: $N processo(s), orçamento ${SEG}s"
[ "$N" -gt 0 ] || exit 0

# 2) um navegador SEI por vez nesta máquina: pausa o sweep da cópia antiga e espera o browser dele soltar
PAUSA="$ANTIGO/data/.pause_sei_sweep"; CRIEI=0
if [ -d "$ANTIGO/data" ] && [ ! -f "$PAUSA" ]; then touch "$PAUSA"; CRIEI=1; fi
trap '[ "$CRIEI" = 1 ] && rm -f "$PAUSA"' EXIT
for _ in $(seq 1 180); do                      # até 30 min (o sei_sweep de lá tem teto de 1300 s)
  pgrep -f 'tools\.sei_swee[p]' >/dev/null || [ -f "$ANTIGO/data/browser.lock" ] || break
  sleep 10
done

# 3) a rodada: código da casa, sem alteração
DESDE=$(stat -c %s "$W/data/sei_integra_fila.log" 2>/dev/null || echo 0)
nice -n 10 ionice -c2 -n6 timeout -k 120 --foreground $((SEG + 1200)) \
  "$PY" tools/sei_integra_fila.py --fila "$FILA" --segundos "$SEG" >> "$LOG" 2>&1
say "sei_integra_fila rc=$?"

# 4) devolve à VM-1 (arquivo + cache da íntegra + linhas do log) e bate o ponto da delegação
"$PY" -m tools.sei_integra_vm2 devolver --desde "$DESDE" >> "$LOG" 2>&1 && \
  ssh -o BatchMode=yes vm1-ts "cd /home/ubuntu/JFN && PYTHONPATH=. .venv/bin/python -m tools.sei_integra_vm2 batida" \
  2>>"$LOG"
say "devolução rc=$? — fim"
