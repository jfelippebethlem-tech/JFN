#!/bin/bash
# fila_analise_sei — os estágios de ANÁLISE do acervo SEI que não usam o browser, cada um no seu cron (14/11/2026).
#
# Antes viviam (ou não viviam) no fim do `sweep_sei.sh`, que só passa ~8×/dia quando a sessão SEI e a carga deixam;
# com a captura dos nós (VM-2, it-campo) entregando dezenas de processos por hora, a análise ficou meses atrás:
# medido em 14/11/2026, de 6.418 processos do acervo, 3.730 sem ficha, 4.165 sem perícia de execução, 3.155 sem
# linha em sei_sigilo. Nenhum destes estágios abre o SEI — rodam à parte, com trava própria (flock: um de cada por
# vez), prioridade baixa e teto de tempo.
#
#   ficha   → tools.sei_ficha_acervo --ciclo     (Haiku pela Batch API, balde extracao_sei, conferência literal)
#   lex     → tools.lex_execucao --top N         (juízo: assinatura + cascata; API paga DESLIGADA aqui — o modelo
#                                                  barato não decide execução, só extrai)
#   sigilo  → tools/sei_inventario_captura.py --gravar   (determinístico)
#
# Pausas: data/.pause_fila_analise (tudo) ou data/.pause_fila_analise_<estágio>.
set -u
cd /home/ubuntu/JFN || exit 1
[ -f .env ] && { set -a; . ./.env; set +a; }
export PYTHONPATH=.
PY=.venv/bin/python
ETAPA=${1:-}
LOG=data/fila_analise_sei.log
say(){ echo "[$(date '+%F %T')] $ETAPA: $*" >> "$LOG"; }

[ -f data/.pause_fila_analise ] && { say "pausado (.pause_fila_analise)"; exit 0; }
[ -f "data/.pause_fila_analise_$ETAPA" ] && { say "pausado (.pause_fila_analise_$ETAPA)"; exit 0; }

case "$ETAPA" in
  ficha)
    exec 9>data/.fila_analise_ficha.lock; flock -n 9 || { say "anterior ainda rodando — pula"; exit 0; }
    nice -n 10 timeout 1500 $PY -m tools.sei_ficha_acervo --ciclo --lote "${FICHA_LOTE:-400}" \
      >> data/sei_ficha_acervo.log 2>&1; say "rc=$?" ;;
  lex)
    exec 9>data/.fila_analise_lex.lock; flock -n 9 || { say "anterior ainda rodando — pula"; exit 0; }
    JFN_CLAUDE_API=0 nice -n 10 timeout 1700 $PY -m tools.lex_execucao --top "${LEX_TOP:-10}" \
      >> data/lex_execucao.log 2>&1; say "rc=$?" ;;
  sigilo)
    exec 9>data/.fila_analise_sigilo.lock; flock -n 9 || { say "anterior ainda rodando — pula"; exit 0; }
    nice -n 19 ionice -c3 timeout 3000 $PY tools/sei_inventario_captura.py --gravar \
      >> data/sei_inventario_captura.log 2>&1; say "rc=$?" ;;
  *) echo "uso: $0 ficha|lex|sigilo" >&2; exit 2 ;;
esac
