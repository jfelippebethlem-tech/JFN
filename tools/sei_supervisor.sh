#!/bin/bash
# sei_supervisor — mantém o SEI sweep VIVO (aos poucos, resumível), análogo ao siafe_supervisor.
# O sei_sweep lê processo a processo (~50s/proc + ficha) e pode morrer por crash do Chromium em runs
# longos; como é RESUMÍVEL (checkpoint data/sei_cache/sei_sweep_progress.json: "feitos"), basta relançar
# em lotes pequenos que ele continua de onde parou.
#
# CPU/lock: o PRÓPRIO sei_sweep já é VM-safe — browser_lock_async (nunca 2 browsers; serializa com o
# SIAFE) + aguardar_load_async(max_por_core=1.5). Então aqui não forço CPU; só relanço o lote.
# Pausa manual: criar data/.pause_sei_sweep (o sweep encerra limpo e o supervisor aguarda).
# Fila vazia: quando o sweep loga "nada novo na fila", faz back-off longo (novos processos vão surgindo
# conforme o SIAFE sweep avança e correlaciona OB↔SEI). Rodar via nohup (é bash, não trava a cota).
cd /home/jfelippebethlem/JFN || exit 1
LOG=data/sei_supervisor.log
OUT=data/sei_cache/sei_sweep_loop.out
LOTE="${SEI_LOTE:-12}"
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

say "sei_supervisor iniciado (lote=$LOTE)"
while true; do
  if [ -f data/.pause_sei_sweep ]; then sleep 120; continue; fi
  # já rodando (ex.: lançado à mão)? não duplica
  if pgrep -f "tools.sei_sweep" >/dev/null; then sleep 60; continue; fi
  # fila esvaziou no último lote → back-off 30min (o SIAFE vai gerando novos processos SEI)
  if tail -3 "$OUT" 2>/dev/null | grep -q "nada novo na fila"; then
    say "fila vazia — back-off 30min (aguardando novos processos do SIAFE)"; sleep 1800; continue
  fi
  say "relançando sei_sweep --max $LOTE"
  PYTHONPATH=. .venv/bin/python -m tools.sei_sweep --max "$LOTE" >> "$OUT" 2>&1
  say "lote concluído (exit $?)"
  sleep 20
done
