#!/usr/bin/env bash
# Finalizador autônomo do enxame de editais: espera o corpus terminar de baixar,
# roda o direcionamento completo (extrai cláusulas → clusters → peer-diff → enxame),
# gera o dossiê PDF e envia no Telegram. VM-safe (só 1 direcionamento por vez).
# Uso: nohup tools/editais_finalizar.sh > data/editais_finalizar.log 2>&1 &
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python

echo "[finalizar] aguardando o corpus terminar…"
while pgrep -f 'tools/editais_corpus.py' >/dev/null; do sleep 120; done
echo "[finalizar] corpus concluído. Estado:"
$PY -c "from compliance_agent.editais import db as ed; c=ed.conectar(); print(c.execute('select count(*), sum(documento_disponivel) from edital_documento').fetchone()[0:2])"

echo "[finalizar] rodando direcionamento completo (clausulas+clusters+enxame)…"
$PY tools/editais_direcionamento.py --clausulas --clusters --max-candidatas 300 --telegram
echo "[finalizar] concluído em $(date -u +%FT%TZ)"
