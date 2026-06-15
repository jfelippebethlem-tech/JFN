#!/usr/bin/env bash
# refresh_favorecido_resumo.sh — rede de segurança decoupled p/ a tabela-resumo `favorecido_resumo`.
# O siafe_runner diário já reconstrói no fim da ingestão; este cron garante frescor mesmo se o diário
# falhar/pular, e CRIA a tabela se faltar (sistema novo). Idempotente (DROP+CREATE+INSERT em BEGIN IMMEDIATE,
# busy_timeout=30000 espera o lock do sweep). VM-safe: nice/ionice + load-guard.
# Cron sugerido (após o siafe das 05:00, antes do sweep_sei das 07:00):
#   45 5 * * *  /home/ubuntu/JFN/tools/refresh_favorecido_resumo.sh >> /home/ubuntu/JFN/data/refresh_favres.log 2>&1
set -u
cd /home/ubuntu/JFN || exit 1
# load-guard: VM de 2 vCPU sem swap — não empilhar
L=$(awk '{print int($1)}' /proc/loadavg)
[ "${L:-0}" -ge 4 ] && { echo "$(date -Is) load alto ($L) — pula"; exit 0; }
nice -n10 ionice -c2 -n6 .venv/bin/python -c \
  "from compliance_agent.reporting.inteligencia import atualizar_favorecido_resumo as a; print('$(date -Is)', a())"
