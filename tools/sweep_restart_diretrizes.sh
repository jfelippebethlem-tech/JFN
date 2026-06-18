#!/bin/bash
# One-shot (sessão): RE-APLICA as novas diretrizes (situacao/lifecycle, Fase 4/5) sobre TODO o corpus já
# coletado, do primeiro processo — preservando cache/DB (sem re-scrape itkava). Ordem de dependência, um
# pesado por vez, baixa prioridade, resumível. NÃO é o sweep itkava (esse segue no cron normal).
set -u
cd /home/ubuntu/JFN || exit 1
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/sweep_restart.log
PRIO="nice -n 10 ionice -c2 -n6"
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
say "=== RESTART diretrizes: início (preserva dados, re-aplica do 1º processo) ==="
# 1) re-ficha TODO o cache com o schema atual (campo situacao) — nous stepfun:free, resumível
$PRIO $PY -m tools.sei_refichar >> "$LOG" 2>&1; say "sei_refichar rc=$?"
# 2) depura fichas -> sei_ficha (com situacao)
$PRIO timeout 600 $PY -m tools.sei_depurar_db >> "$LOG" 2>&1; say "sei_depurar rc=$?"
# 3) consolida árvores -> sei_arvore (lifecycle/encerrado a partir da situacao)
$PRIO timeout 900 $PY -m tools.sei_arvore_build >> "$LOG" 2>&1; say "sei_arvore rc=$?"
# 4) memória cruzada de direcionamento por fornecedor
$PRIO timeout 400 $PY -m tools.sei_direcionamento_varre >> "$LOG" 2>&1; say "sei_direc_varre rc=$?"
# 5) direcionamento LLM on-demand (Fase 4) nos top-score
$PRIO timeout 900 $PY -m tools.sei_direcionamento_llm --top 10 >> "$LOG" 2>&1; say "sei_direc_llm rc=$?"
# 6) pesquisa-internet (Fase 5) nos top-score: aprende (vault/DB) + re-ajusta
$PRIO timeout 1200 $PY -m tools.lex_pesquisa_internet --top 5 >> "$LOG" 2>&1; say "lex_pesquisa rc=$?"
say "=== RESTART diretrizes: FIM ==="
