#!/bin/bash
# Dispara o OCR em CPU do it-campo (deploy/itcampo/ocr_cpu/ocr_cpu.sh) a partir da VM-1 — cron, single-pass.
# O script vai pela entrada padrão do WSL (mesma via da sonda de pulso): nada fica instalado fora do controle do git.
set -u
J=/home/ubuntu/JFN
exec 9>"$J/data/locks/itcampo_ocr_cpu.lock"
flock -n 9 || exit 0
[ -e "$J/data/.pause_ocr_reserva" ] && exit 0
echo "[$(date '+%F %T')] início"
timeout -k 60 2100 ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=60 it-campo \
    'wsl -d Ubuntu -- bash -s 2 6 1500' < "$J/deploy/itcampo/ocr_cpu/ocr_cpu.sh"
echo "[$(date '+%F %T')] fim rc=$?"
