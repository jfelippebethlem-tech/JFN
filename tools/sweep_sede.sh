#!/usr/bin/env bash
# sweep_sede.sh — verificação de SEDE REAL sem Google e sem Mapillary.
#
# 2026-07-23: o motor Google (Places/Street View/Geocoding) foi APOSENTADO. Desde o
# desligamento do billing (25/06) ele rodava em VAZIO — 1.272 endereços por ciclo,
# 0 foto, ~22 min de CPU por nada. O caminho antigo continua em
# tools/sweep_sede_google.py; para voltar a ele basta trocar a linha do exec.
#
# O motor novo (tools/sweep_sede_real.py) troca foto por base cadastral: 6,17 mi de
# estabelecimentos da Receita indexados por prédio, ~7 ms por CNPJ, offline, R$ 0,00.
set -u
cd /home/ubuntu/JFN || exit 1
[ -f data/.pause_sede_sweep ] && { echo "$(date -Is) pausado (.pause_sede_sweep)"; exit 0; }
# load-guard: VM de 2 vCPU — não empilhar
L=$(awk '{print int($1)}' /proc/loadavg)
[ "${L:-0}" -ge 4 ] && { echo "$(date -Is) load alto ($L) — pula"; exit 0; }
exec flock -n data/.sweep_sede.lock \
  nice -n10 ionice -c2 -n6 timeout 1800 \
  .venv/bin/python -m tools.sweep_sede_real --max-segundos 1500
