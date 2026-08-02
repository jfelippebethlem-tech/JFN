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
from pathlib import Path
con = sqlite3.connect("file:data/compliance.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
# "já julgado" = julgado na rubrica VIGENTE. Fixar '2' aqui deixaria o sweep pulando processos
# que só têm veredito de uma rubrica velha — e a v3 (2026-08-02) mudou o que conta como vício.
# Ler a constante do módulo evita esta linha envelhecer calada de novo.
from compliance_agent.sei.doc_juizo import RUBRICA_VERSAO, RUBRICAS
from compliance_agent.sei import manifesto_norm
# A fila raciocina por DOCUMENTO, não por processo. Com o critério antigo (distinct numero_sei),
# um processo com um único despacho julgado ficava "pronto" para sempre — e as peças que ganharam
# rubrica depois (autorização de despesa, TR, pesquisa de preços: 1.398 documentos no acervo)
# nunca seriam avaliadas em nenhum dos processos já visitados.
julgados = {}
for sei, doc_i in con.execute(
        "select numero_sei, doc_i from doc_veredito where rubrica_versao=?", (RUBRICA_VERSAO,)):
    julgados.setdefault(sei, set()).add(doc_i)
fila = []
for r in con.execute("select * from processo_avaliacao"):
    pts, _ = pontuar(json.loads(r["achados_json"] or "[]"),
                     json.loads(r["acatamento_json"] or "{}"))
    if pts >= 5:
        fila.append((pts, r["numero_sei"]))
con.close()
fila.sort(reverse=True)

def tem_pendente(numero):
    """Sobrou documento elegível por rubrica sem veredito na versão vigente?"""
    feitos = julgados.get(numero)
    if feitos is None:
        return True                      # nunca julgado
    pasta = Path("data/sei_arquivo") / numero.replace("/", "_")
    if not (pasta / "manifest.json").exists():
        return False                     # sem arquivo local não há o que julgar
    try:
        man = manifesto_norm.normalizar(
            {**json.loads((pasta / "manifest.json").read_text(encoding="utf-8")),
             "_pasta": str(pasta)})
    except Exception:
        return False
    return any(d.get("tipo") in RUBRICAS and d.get("i") not in feitos for d in man["docs"])

alvos = []
for _, numero in fila:
    if tem_pendente(numero):
        alvos.append(numero)
    if len(alvos) >= 4:
        break
for numero in alvos:
    subprocess.run([".venv/bin/python", "tools/processo_360.py", "--numero", f"SEI-{numero}",
                    "--com-llm", "--gravar"], timeout=380)
PYEOF
say "360 juizo rc=$?"

# 3) fila do fiscal regravada (top do ranking por QUALIDADE do achado, não pelo score cru)
$PRIO timeout 120 $PY tools/processo_360_ranking.py --top 40 --md > data/fila_fiscal_360.md 2>>"$LOG"
say "ranking rc=$? -> data/fila_fiscal_360.md"
