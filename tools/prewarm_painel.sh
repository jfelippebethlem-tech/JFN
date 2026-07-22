#!/bin/bash
# Pré-aquece os caches dos endpoints PESADOS do painel (medidos no walker 2026-07-22:
# fornecedor_dependente 23s, frescor 14s, perícias 7s, sócio-servidor 6.5s frios).
# O humano nunca mais espera o frio: o cron paga o custo em background (nice), o
# painel responde em ms. TTLs analíticos = 3600s; cron a cada 30min mantém sempre quente.
set -u
LOG=/home/ubuntu/JFN/data/prewarm_painel.log
exec 9>/tmp/prewarm_painel.lock
flock -n 9 || exit 0
BASE="http://127.0.0.1:8000/api"
URLS=(
  "intel/fornecedor_dependente?limite=150"
  "fontes/frescor"
  "pericias?limite=80&ordem=score"
  "intel/socio_servidor?limite=150"
  "intel/nepotismo_cruzado?limite=80"
  "intel/nepotismo?limite=150"
  "intel/retro"
  "intel/porta_giratoria?limite=150"
  "pncp/conluio?esfera=estado"
  "pncp/conluio?esfera=prefeitura"
  "pncp/conluio"
  "cartel"
  "compliance/painel"
  "certames/lista?esfera=prefeitura&limite=600"
  "certames/lista?esfera=estado&limite=600"
)
{
  echo "── $(date -Is) prewarm"
  for u in "${URLS[@]}"; do
    t=$(nice -n 15 curl -s -o /dev/null -w "%{http_code} %{time_total}" "$BASE/$u")
    echo "  $t $u"
  done
} >> "$LOG" 2>&1
# trava o log em ~2000 linhas (sem logrotate dedicado)
tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
