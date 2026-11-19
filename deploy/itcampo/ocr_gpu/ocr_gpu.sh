#!/bin/bash
# Lançador do OCR por IA (GPU). Sobe o vLLM do Surya se não estiver no ar e roda o trabalhador (retoma sozinho).
set -u
mkdir -p ~/jfn-gpu/ocr
cp -n /mnt/c/Users/iterj/ocr_fila.txt ~/jfn-gpu/ocr/ocr_fila.txt 2>/dev/null || true
cp /mnt/c/Users/iterj/ocr_gpu_worker.py ~/jfn-gpu/ocr_gpu_worker.py
bash /mnt/c/Users/iterj/vllm_surya.sh | grep -E "PRONTO|checkpoint"
cd ~/jfn-gpu
MALLOC_ARENA_MAX=2 SURYA_INFERENCE_URL=http://127.0.0.1:8790/v1 nice -n 10 .venv/bin/python -u ocr_gpu_worker.py
