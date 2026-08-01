#!/bin/bash
# sweep_360 — mantém a avaliação de PROCESSO em dia e a fila do fiscal fresca.
#
# Complementa o sweep_sei (que CAPTURA) com o que AVALIA: todo processo recém-arquivado ganha
# avaliação 360 determinística; o topo da fila ganha o juízo por documento (rubrica fechada,
# cadeia grátis). Bounded, nice/ionice idle, single-pass (o cron repete). Respeita as mesmas
# pausas do sweep_sei e NUNCA roda junto de outro escritor do compliance.db (lock por arquivo).
set -u
cd /home/ubuntu/JFN || exit 1
[ -f .env ] && { set -a; . ./.env; set +a; }
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/sweep_360.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

[ -f data/.pause_sweeps ] && { say "pausado (.pause_sweeps)"; exit 0; }
[ -f data/.pause_360 ] && { say "pausado (.pause_360)"; exit 0; }

# lock: 1 escritor por vez no compliance.db (dois escritores já mataram um lote — 2026-08-01)
LOCK=data/.lock_360
if ! mkdir "$LOCK" 2>/dev/null; then
  say "outro sweep_360 em curso — pulei"; exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

PRIO="nice -n 19 ionice -c3"

# 1) avaliação determinística dos processos ainda não avaliados (ou desatualizados)
$PRIO timeout -k 60 --foreground 1200 $PY tools/processo_360.py --lote 120 --gravar \
  >> data/sweep_360_lote.out 2>&1; say "360 lote rc=$?"

# 2) juízo por documento no topo da fila (rubrica fechada; cadeia grátis com teto diário próprio).
#    Poucos por slot: qualidade > volume, e o cache por hash torna a repetição barata.
$PRIO timeout -k 60 --foreground 1500 $PY - <<'PYEOF' >> data/sweep_360_llm.out 2>&1
import subprocess, sys
sys.path.insert(0, ".")
from tools.processo_360_ranking import pontuar
import json, sqlite3
con = sqlite3.connect("file:data/compliance.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
julgados = {r[0] for r in con.execute(
    "select distinct numero_sei from doc_veredito where rubrica_versao='2'")}
fila = []
for r in con.execute("select * from processo_avaliacao"):
    if r["numero_sei"] in julgados:
        continue
    pts, _ = pontuar(json.loads(r["achados_json"] or "[]"),
                     json.loads(r["acatamento_json"] or "{}"))
    if pts >= 5:
        fila.append((pts, r["numero_sei"]))
con.close()
fila.sort(reverse=True)
for _, numero in fila[:4]:
    subprocess.run([".venv/bin/python", "tools/processo_360.py", "--numero", f"SEI-{numero}",
                    "--com-llm", "--gravar"], timeout=380)
PYEOF
say "360 juizo rc=$?"

# 3) fila do fiscal regravada (top do ranking por QUALIDADE do achado, não pelo score cru)
$PRIO timeout 120 $PY tools/processo_360_ranking.py --top 40 --md > data/fila_fiscal_360.md 2>>"$LOG"
say "ranking rc=$? -> data/fila_fiscal_360.md"
