#!/bin/bash
# Guard de OOM: este sweep morre ANTES da sessão do dono (ver tools/lib/oom_guard.sh).
source "$(dirname "$0")/lib/oom_guard.sh" 2>/dev/null || true
# cruzador — ao FIM do dia, CRUZA todos os dados coletados: OB↔SEI (correlacao_sei) + concentração por grupo
# econômico (cartel/diversidade fictícia). Roda SOZINHO à noite → sem sweep competindo → DuckDB seguro.
# LEVE: nice/ionice idle, bounded.
set -u
cd /home/ubuntu/JFN || exit 1
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/cruzador.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

[ -f data/.pause_sweeps ] && { say "pausado (.pause_sweeps) — pulei este ciclo"; exit 0; }
# VM = 2 vCPU / 7,8GB / SEM swap → roda à NOITE sozinho; backstop se algo pesado ainda estiver vivo
L=$(awk '{print int($1)}' /proc/loadavg); [ "$L" -ge 4 ] && { say "load $L alto — adia cruzador"; exit 0; }
PRIO="nice -n 10 ionice -c2 -n6"
say "início — cruzando dados"
# 1) OB ↔ SEI (processo ↔ pagamentos)
$PRIO timeout 1200 $PY -m compliance_agent.correlacao_sei >> "$LOG" 2>&1; say "correlacao_sei rc=$?"
# 1b) íntegras PNCP × extratos do D.O. Rio → contrato_doe_evento/contrato_doe_sinal (emergência no incumbente, direta, valor divergente)
$PRIO timeout 900 $PY -m tools.pcrj_integra_x_doe >> "$LOG" 2>&1; say "pcrj_integra_x_doe rc=$?"
# 1c) DOERJ: Termos de Ajuste de Contas recorrentes (quem recebe sem contrato, quantas vezes, quanto) → doerj_tac
$PRIO timeout 600 $PY -m tools.doerj_tac_recorrente --top 5 >> "$LOG" 2>&1; say "doerj_tac_recorrente rc=$?"
# 1d) TAC × favorecimento (agente público no QSA, sócio comum, capital ínfimo, fachada, emergência recorrente, doação) → doerj_tac_sinal
$PRIO timeout 900 $PY -m tools.doerj_tac_favorecimento --top 5 >> "$LOG" 2>&1; say "doerj_tac_favorecimento rc=$?"
# 1e) contratadas da FSERJ (contrato + TAC) com sócio na folha da saúde estadual → fserj_socio_agente
$PRIO timeout 600 $PY -m tools.fserj_socio_agente --top 5 >> "$LOG" 2>&1; say "fserj_socio_agente rc=$?"
# 2) concentração por grupo econômico nas 60 maiores UGs (cartel oculto) — DuckDB pesado, mas SOZINHO à noite
$PRIO timeout 1800 $PY - >> "$LOG" 2>&1 <<'PYEOF'
from compliance_agent import grafo_cartel as gc
from compliance_agent.duckdb_util import conectar
con = conectar()
ugs = [r[0] for r in con.execute("SELECT ug_codigo FROM db.ordens_bancarias WHERE valor>0 AND ug_codigo IS NOT NULL GROUP BY ug_codigo ORDER BY SUM(valor) DESC LIMIT 60").fetchall()]
con.close()
ach = 0
for ug in ugs:
    try:
        r = gc.concentracao_por_grupo(str(ug))
        if r.get("indicio"):
            ach += 1
            gs = [g for g in r.get("grupos", []) if g.get("n_cnpjs", 1) > 1]
            dom = max(gs, key=lambda g: g.get("share", 0)) if gs else {}
            print(f"[cruzador] CARTEL? UG {ug} {r.get('ug_nome','')[:32]} | grupo {dom.get('n_cnpjs')} CNPJ = {dom.get('share',0):.0f}%")
    except Exception:
        pass
print(f"[cruzador] concentração-grupo: {ach}/60 UGs com indício")
PYEOF
say "concentracao-grupo rc=$?"
say "fim"
