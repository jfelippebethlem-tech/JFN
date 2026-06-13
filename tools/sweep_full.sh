#!/bin/bash
# sweep_full — COBERTURA TOTAL (pedido do dono): endereço + fachada DD + CPF/sócios de TODOS os fornecedores de
# TODAS as UGs. Diferente dos sweeps de rotação (1 UG/cauda por vez), este DRENA o universo inteiro.
# VM-SAFE (2 vCPU / sem swap — lição OOM): nice/ionice, load-guard (espera se load≥3), slices bounded por timeout,
# SERIALIZADO (nunca 2 pesados juntos), resumível (tabelas + cache + done-file da fachada), time-bounded (sai após
# MAXH; relançar continua de onde parou). NÃO roda concorrente com cruzador/DuckDB.
set -u
cd /home/jfelippebethlem/JFN || { echo "cd falhou"; exit 1; }
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/sweep_full.log
DONE=data/.sweep_full_fachada_done   # UGs de fachada já cobertas (resumível)
PRIO="nice -n 10 ionice -c2 -n6"
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
guard(){ local L; L=$(awk '{print int($1)}' /proc/loadavg); while [ "$L" -ge 3 ]; do say "load $L alto — aguardando 60s"; sleep 60; L=$(awk '{print int($1)}' /proc/loadavg); done; }

[ -f data/.pause_sweeps ] && { say "pausado (.pause_sweeps) — saí"; exit 0; }
# lock ATÔMICO (flock) — single-instance sem race (o pgrep self-check matava ambos numa corrida)
exec 9>data/.sweep_full.lock
flock -n 9 || { say "já há sweep_full rodando (lock ocupado) — saí"; exit 0; }
touch "$DONE"

MAXH=${1:-6}
FIM=$(( $(date +%s) + MAXH*3600 ))
say "==== início cobertura total (até ${MAXH}h) ===="

# Todas as UGs por volume de R$ (cauda = onde mora fachada, mas aqui cobrimos TODAS)
UGS=$($PY -c "import sqlite3;c=sqlite3.connect('data/compliance.db').cursor();print(' '.join(str(r[0]) for r in c.execute(\"SELECT ug_codigo FROM ordens_bancarias WHERE valor>0 AND ug_codigo IS NOT NULL GROUP BY ug_codigo ORDER BY SUM(valor) DESC\").fetchall()))" 2>/dev/null)
say "UGs alvo: $(echo $UGS | wc -w)"

while [ "$(date +%s)" -lt "$FIM" ]; do
  algo=0

  # 1) ENDEREÇO — drena o gap (endereco_fornecedor sem verificação)
  guard
  out=$($PRIO timeout 1200 $PY -m tools.backfill_verificacao_endereco --limite 200 --pausa 0.3 2>&1 | grep -E 'a verificar|FIM lote' | tail -1)
  say "endereço → ${out:-(sem saída)}"
  echo "$out" | grep -qE '^\[.*\] 0 fornecedor|FIM lote: 0 ' || algo=1

  # 2) SÓCIOS/CPF — drena sócios não resolvidos (resolve CPF + benefícios)
  guard
  out=$($PRIO timeout 1200 $PY -m tools.beneficios_sweep --limite 400 --pausa 0.3 2>&1 | grep -E 'socios processados|resolvidos' | tail -1)
  say "sócios/cpf → ${out:-(sem saída)}"
  echo "$out" | grep -q '0 socios processados' || algo=1

  # 3) FACHADA — próxima UG ainda não coberta (TODOS os fornecedores: --limite 0, sem max-valor)
  prox=""
  for ug in $UGS; do grep -qx "$ug" "$DONE" || { prox=$ug; break; }; done
  if [ -n "$prox" ]; then
    guard
    $PRIO timeout 1500 $PY -m tools.dd_sweep_orgao "$prox" --limite 0 --pausa 0.3 >> data/dd_sweep/full_${prox}.log 2>&1
    rc=$?
    [ $rc -eq 0 ] && echo "$prox" >> "$DONE"
    say "fachada UG $prox rc=$rc ($(grep -cx . "$DONE" 2>/dev/null)/$(echo $UGS|wc -w) UGs cobertas)"
    algo=1
  else
    say "fachada: todas as UGs cobertas ✓"
  fi

  if [ "$algo" = "0" ]; then say "==== nada novo a fazer — cobertura COMPLETA ===="; break; fi
done
say "==== fim da passada (tempo esgotado ou completo) ===="
