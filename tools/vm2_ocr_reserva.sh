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
# Freio medido 18/11/2026: VM-2 sem swap (um bench de 5,7 GB levou OOM) e pico de 1,1 GB por PDF real → memória
# livre >= 2,5 GB antes de cada PDF. Load: a VM-2 vive em 3–7 (indexador do brain + navegador SEI); com nice 19 a
# reserva só usa CPU ociosa, então o teto é 2,5 por núcleo (5,0), não 1,5 — com 1,5 ela nunca rodaria.
export JFN_OCR_MEM_MIN_GB=2.5 JFN_OCR_LOAD_POR_NUCLEO=2.5
exec 9>"$W/data/.ocr_reserva.lock"
flock -n 9 || { echo "[$(date '+%F %T')] rodada anterior viva — pula" >> "$LOG"; exit 0; }
git -C "$W" pull --ff-only -q 2>>"$LOG" || echo "[$(date '+%F %T')] git pull falhou — segue com $(git -C "$W" rev-parse --short HEAD)" >> "$LOG"
echo "[$(date '+%F %T')] início $(git -C "$W" rev-parse --short HEAD)" >> "$LOG"
cd "$W" && timeout -k 60 3300 nice -n 19 ionice -c3 "$PY" -m tools.sei_ocr_reserva rodar --orcamento 3000 --n 12 --no vm2 >> "$LOG" 2>&1
echo "[$(date '+%F %T')] fim rc=$?" >> "$LOG"
