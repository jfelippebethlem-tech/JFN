#!/bin/bash
# sweep_avaliacao_total — a AVALIAÇÃO de tudo que a casa coleta, sem ninguém pedir.
#
# O pedido do dono (2026-08-01): "que autonomamente o sistema todo funcione, avaliando cada OB,
# contrato, licitação, execução". Os coletores já rodam (siafe_runner, sweep_sei, sweep_dados);
# o que faltava era a AVALIAÇÃO das quatro superfícies rodando sozinha e deixando fila pronta:
#
#   OB/pagamento .......... anomalias (ob_redflag) + regras (alertas) + perícia por fornecedor
#   licitação/certame ..... varredura_certames (E/J/P) — grava em achados.db
#   contrato/execução ..... varredura_execucao (X1..X13)
#   órgão ................. varredura_orgaos (J1 cartel + C fachada)
#   processo (autos) ...... sweep_360.sh, que roda em cron próprio (20 */4)
#
# DISCIPLINA DA CASA: bounded por timeout, nice/ionice idle, UM escritor por vez (lock),
# pausável por arquivo, e NUNCA junto do enxame de editais (que trava as rotas de leitura).
set -u
cd /home/ubuntu/JFN || exit 1
[ -f .env ] && { set -a; . ./.env; set +a; }
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/sweep_avaliacao.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

[ -f data/.pause_sweeps ] && { say "pausado (.pause_sweeps)"; exit 0; }
[ -f data/.pause_avaliacao ] && { say "pausado (.pause_avaliacao)"; exit 0; }

LOCK=data/.lock_avaliacao
mkdir "$LOCK" 2>/dev/null || { say "outra avaliação em curso — pulei"; exit 0; }
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# não concorrer com o 360 pelo mesmo banco (1 escritor por vez — lição de 2026-08-01)
[ -d data/.lock_360 ] && { say "sweep_360 em curso — adiado p/ o próximo slot"; exit 0; }

PRIO="nice -n 19 ionice -c3"

# 1) OB/PAGAMENTO — anomalias determinísticas sobre as ordens bancárias (recomputa ob_redflag)
$PRIO timeout -k 60 --foreground 900 $PY -m compliance_agent.anomalias --rodar \
  >> data/sweep_aval_ob.out 2>&1; say "ob_anomalias rc=$?"

# 2) OB/ALERTAS — motor de regras da casa (grava em `alertas`)
$PRIO timeout -k 60 --foreground 900 $PY analisar.py --rodar \
  >> data/sweep_aval_regras.out 2>&1; say "regras rc=$?"

# 3) LICITAÇÃO/CERTAME — detectores E/J/P sobre os certames ainda não varridos.
#    Sem CLI própria (varrer_todos é biblioteca): invocação inline, mesma disciplina de teto.
$PRIO timeout -k 60 --foreground 1200 $PY -c "
import sqlite3
from compliance_agent.varredura_certames import varrer_todos, init_schema
con = sqlite3.connect('data/compliance.db', timeout=60); con.execute('PRAGMA busy_timeout=60000')
ach = sqlite3.connect('data/achados.db', timeout=60); init_schema(ach)
r = varrer_todos(con, limite=60, con_achados=ach, log=print)
print('certames:', {k: v for k, v in r.items() if k != 'por_certame'})
" >> data/sweep_aval_certames.out 2>&1; say "certames rc=$?"

# 4) CONTRATO/EXECUÇÃO — X1..X13 sobre os contratos com aditivo/pagamento
$PRIO timeout -k 60 --foreground 1200 $PY -m compliance_agent.varredura_execucao --limite 120 --gravar \
  >> data/sweep_aval_execucao.out 2>&1; say "execucao rc=$?"

# 5) ÓRGÃO — cartel por grupo (J1) + perfil dos fornecedores da UG (idem: biblioteca, não CLI)
$PRIO timeout -k 60 --foreground 1200 $PY -c "
import sqlite3
from compliance_agent.varredura_orgaos import varrer_todas, init_schema
con = sqlite3.connect('data/compliance.db', timeout=60); con.execute('PRAGMA busy_timeout=60000')
ach = sqlite3.connect('data/achados.db', timeout=60); init_schema(ach)
r = varrer_todas(con, limite_ugs=8, max_fornecedores=15, con_achados=ach, log=print)
print('orgaos:', {k: v for k, v in r.items() if k != 'por_ug'})
" >> data/sweep_aval_orgaos.out 2>&1; say "orgaos rc=$?"

# 6) FORNECEDOR — perícia contábil (T01–T25) de quem tem massa de OB e ainda não foi periciado
$PRIO timeout -k 60 --foreground 1500 $PY -m compliance_agent.pericia_sweep --min-obs 6 --limit 40 \
  >> data/sweep_aval_pericia.out 2>&1; say "pericia rc=$?"

# 7) SCREENS DE CARTEL (Cardinal/OCP + convergência da casa) — fila de licitantes p/ o fiscal
$PRIO timeout 300 $PY tools/screen_convergencia_cartel.py --md > data/fila_cartel.md 2>>"$LOG"
say "screens rc=$? -> data/fila_cartel.md"
