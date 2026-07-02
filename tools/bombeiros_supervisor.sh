#!/bin/bash
# bombeiros_supervisor — mantém VIVA a perícia paralela (Lex×Claude) dos 1.638 contratos do FUNESBOM,
# em ORDEM DE SUSPEITA, resumível e VM-safe. Análogo ao sei_supervisor, dedicado aos bombeiros.
# Ciclo por lote: coleta SEI (canônico, browser_lock) -> depura ficha -> monta árvore/dossiê ->
# Lex pericia -> camada Claude (reconciliação). Sem Gemini (GEMINI_DISABLED=1; ficha=stepfun:free).
# Pausa: criar data/.pause_bombeiros. Parar: kill deste script + do python.  Resumível: o checkpoint
# data/sei_cache/sei_sweep_progress.json guarda os já lidos; relançar continua de onde parou.
cd /home/ubuntu/JFN || exit 1
echo $$ > data/bombeiros_supervisor.pid
LOG=data/bombeiros_supervisor.log
PY=".venv/bin/python"; export PYTHONPATH=.
LOTE="${BBM_LOTE:-10}"
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
say "bombeiros_supervisor iniciado (lote=$LOTE)"
while true; do
  if [ -f data/.pause_bombeiros ]; then sleep 120; continue; fi
  # nunca 2 browsers: se o sweep principal estiver lendo, espera (browser_lock já serializa, mas evita thrash)
  if pgrep -f "tools.sei_sweep" >/dev/null || pgrep -f "tools.sei_bombeiros_sweep" >/dev/null; then sleep 60; continue; fi
  # 1) COLETA um lote em ordem de prioridade
  $PY -m tools.sei_bombeiros_sweep --max "$LOTE" >> data/bombeiros_sweep.out 2>&1
  rc=$?; say "sweep lote rc=$rc"
  # fila drenada? o sweep loga "nada novo na fila" → back-off longo e revalida
  if tail -3 data/bombeiros_sweep.out 2>/dev/null | grep -q "nada novo na fila"; then
    say "fila aparentou drenada — back-off 20min"; sleep 1200; continue; fi
  # 2) ficha -> tabela ; 3) dossiê/árvore ; 4) Lex pericia (novas fichas) ; 5) camada Claude
  timeout 300 $PY -m tools.sei_depurar_db   >> data/sei_depurar.log 2>&1; say "depurar rc=$?"
  timeout 400 $PY -m tools.sei_arvore_build >> data/sei_arvore.log  2>&1; say "arvore rc=$?"
  # 3b) atualiza o CORPUS de íntegra+OCR (cache-only, SEM browser) → alimenta direcionamento IRM/bombeiros
  timeout 300 $PY -m tools.bombeiros_integra_supervisor >> data/bombeiros_integra.log 2>&1; say "integra rc=$?"
  # 3c) ARQUIVO compacto: integra->txt+fotos de medicao+fases (cache-only, SEM browser)
  #     consulta depois: tools/sei_consultar.py - ver docs/PLAYBOOK-SEI.md
  timeout 400 $PY tools/sei_arquivar.py --pendentes >> data/sei_arquivar.log 2>&1; say "arquivar rc=$?"
  timeout 600 $PY -m tools.lex_bombeiros --max 20 >> data/bombeiros_lex.out 2>&1; say "lex rc=$?"
  # 5b) acha a LICITAÇÃO (pregão/edital) nos docs coletados e a enfileira (família 270xxx) → destrava
  #     direcionamento (ata) + sobrepreço (TR/itens) ao coletar o edital no próximo lote.
  $PY tools/bombeiros_achar_edital.py >> data/bombeiros_edital.out 2>&1; say "achar_edital rc=$?"
  # 6) camada Claude (reconciliação Lex×Claude)
  $PY tools/pericia_bombeiros_reconcilia.py >> data/bombeiros_reconcilia.out 2>&1; say "reconcilia rc=$?"
  sleep 15
done
