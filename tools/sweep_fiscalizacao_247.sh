#!/bin/bash
# Guard de OOM: este sweep morre ANTES da sessão do dono (ver tools/lib/oom_guard.sh).
source "$(dirname "$0")/lib/oom_guard.sh" 2>/dev/null || true
#
# sweep_fiscalizacao_247 — a fiscalização contínua, em três camadas.
#
# Responde ao pedido "que as outras ias rodem e identifiquem irregularidades 24/7". O desenho e
# o porquê de cada camada estão em `compliance_agent/llm/camada_triagem.py`.
#
# O QUE RODA, em ordem, e por quê nessa ordem:
#   1. varredura ÓRGÃO A ÓRGÃO (determinística, sem IA)  — barata, cobre tudo, é onde o volume morre
#   2. triagem de FRACIONAMENTO na fonte SIAFE            — fila de candidatos do exercício corrente
#   3. camada 2 (IA em rubrica fechada) só se houver orçamento e nenhuma pausa
#
# COMO PARAR, sem deploy e sem mexer no cron:
#   touch data/.pause_sweeps            # para TODOS os sweeps da casa
#   touch data/.pause_fiscalizacao      # para só este
#   touch data/.pause_llm_triagem       # mantém a camada 1 e desliga só a IA
#
# BOUNDED por natureza: `timeout` em cada passo, `nice`/`ionice` de baixa prioridade, e o guard
# de OOM no topo. A VM tem 2 vCPU — um passo pesado por vez, sempre.
set -u
cd /home/ubuntu/JFN || exit 1
[ -f .env ] && { set -a; . ./.env; set +a; }
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/fiscalizacao_247.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

[ -f data/.pause_sweeps ] && { say "pausado (.pause_sweeps)"; exit 0; }
[ -f data/.pause_fiscalizacao ] && { say "pausado (.pause_fiscalizacao)"; exit 0; }
# Não abrir uma segunda varredura por cima da anterior (o cron repete; a fila não se perde).
if pgrep -f 'varredura_orgaos_swee[p]' >/dev/null; then say "já rodando — pula"; exit 0; fi
# Backstop de VM: com a máquina carregada, adia. O cron volta no próximo slot.
L=$(awk '{print int($1)}' /proc/loadavg); [ "$L" -ge 4 ] && { say "load $L alto — adia"; exit 0; }

PRIO="nice -n 12 ionice -c2 -n7"
ANO=$(date +%Y)
say "início (exercício $ANO)"

# ── CAMADA 1 — determinística. `--limite-ugs` mantém cada execução curta; como a persistência é
# idempotente (INSERT OR REPLACE), as execuções sucessivas cobrem a fila inteira ao longo do dia.
IA=""
[ -f data/.pause_llm_triagem ] || IA="--com-ia"
$PRIO timeout -k 60 1800 $PY tools/varredura_orgaos_sweep.py \
      --exercicio "$ANO" --limite-ugs 25 --max-fornecedores 12 --gravar $IA \
      >> data/varredura_orgaos.log 2>&1
say "varredura_orgaos rc=$? (camada 2: ${IA:-desligada})"

# ── Fila de fracionamento do exercício corrente (leitura do SIAFE; sem IA).
$PRIO timeout -k 60 900 $PY tools/fracionamento_siafe_sweep.py \
      --exercicio "$ANO" --gravar --top 0 >> data/fracionamento_siafe.log 2>&1
say "fracionamento_siafe rc=$?"

# ── Uso da camada 2 no dia, para a conta ser auditável em vez de estimada.
$PY -c "
from compliance_agent.llm.camada_triagem import status
s = status()
print(f\"camada2 chamadas={s['chamadas_hoje']}/{s['teto_dia']} ok={s['ok']} \"
      f\"vazias={s['vazias']} erros={s['erros']} restante={s['restante']}\")
" >> "$LOG" 2>&1

say "fim"
