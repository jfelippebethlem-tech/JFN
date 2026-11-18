#!/bin/bash
# OCR de RESERVA na VM-2 (clone git ~/JFN-worker). Desenho e prova de não-duplicação: tools/sei_ocr_reserva.py.
# Forma da casa: single-pass com teto (timeout -k), flock contra cópia dupla, nice 19 + ionice idle (a captura SEI
# desta máquina tem prioridade; o próprio script cede com load/memória altos). Sem `while true`.
# Agendado por deploy/vm2/jfn-ocr-reserva-vm2.timer. Pausa: ~/JFN-worker/data/.pause_ocr_reserva (só este nó)
# ou ~/JFN/data/.pause_ocr_reserva na VM-1 (todos os nós).
set -u
W=/home/ubuntu/JFN-worker
PY=/home/ubuntu/ocr-reserva/.venv/bin/python     # venv próprio: rapidocr 3.10 + onnxruntime 1.32 + pymupdf
LOG="$W/data/vm2_ocr_reserva.log"
export TZ=America/Sao_Paulo PYTHONPATH="$W" JFN_OCR_RESERVA_DIR=/home/ubuntu/ocr-reserva
exec 9>"$W/data/.ocr_reserva.lock"
flock -n 9 || { echo "[$(date '+%F %T')] rodada anterior viva — pula" >> "$LOG"; exit 0; }
git -C "$W" pull --ff-only -q 2>>"$LOG" || echo "[$(date '+%F %T')] git pull falhou — segue com $(git -C "$W" rev-parse --short HEAD)" >> "$LOG"
echo "[$(date '+%F %T')] início $(git -C "$W" rev-parse --short HEAD)" >> "$LOG"
cd "$W" && timeout -k 60 3300 nice -n 19 ionice -c3 "$PY" -m tools.sei_ocr_reserva rodar --orcamento 3000 --n 12 --no vm2 >> "$LOG" 2>&1
echo "[$(date '+%F %T')] fim rc=$?" >> "$LOG"
