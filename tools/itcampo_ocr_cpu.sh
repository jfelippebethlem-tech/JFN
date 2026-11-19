#!/bin/bash
# Dispara o OCR em CPU do it-campo (deploy/itcampo/ocr_cpu/ocr_cpu.sh) a partir da VM-1 — cron, single-pass.
# O script vai pela entrada padrão do WSL (mesma via da sonda de pulso): nada fica instalado fora do controle do git.
set -u
J=/home/ubuntu/JFN
exec 9>"$J/data/locks/itcampo_ocr_cpu.lock"
flock -n 9 || exit 0
# Estado do it-campo (GPU, RAM do Windows e do WSL, sessões SEI, pool nativo) que o pool do Windows grava a cada 30 s
# (deploy/itcampo/nativo/pool_nativo.py) → data/itcampo_estado.json, lido pelo painel (Sistema). Troca atômica.
timeout 60 scp -q -o BatchMode=yes -o ConnectTimeout=15 it-campo:C:/JFN-Nativo/estado.json "$J/data/itcampo_estado.json.tmp" \
    && mv -f "$J/data/itcampo_estado.json.tmp" "$J/data/itcampo_estado.json"
[ -e "$J/data/.pause_ocr_reserva" ] && exit 0
echo "[$(date '+%F %T')] início"
timeout -k 60 2100 ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=60 it-campo \
    'wsl -d Ubuntu -- bash -s 2 6 1500' < "$J/deploy/itcampo/ocr_cpu/ocr_cpu.sh"
echo "[$(date '+%F %T')] fim rc=$?"
