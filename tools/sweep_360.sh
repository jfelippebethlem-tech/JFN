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

# 1 PESADO POR VEZ (regra absoluta da casa — a VM tem 2 vCPU e já caiu 4×). O slot do juízo passou
# de 4 processos para até 40 min de trabalho contínuo; sem esta guarda ele passaria a disputar CPU
# com o sweep SEI (Chromium + tesseract) que roda de 30 em 30 minutos. Mesmo critério do
# sweep_sei.sh: adia em vez de brigar — o cron repete, nada se perde.
if pgrep -f 'tools\.sei_swee[p]' >/dev/null; then
  say "sweep SEI em curso — adio o juízo (1 pesado por vez)"; JUIZO_SEGUNDOS=0
fi
L=$(awk '{print int($1)}' /proc/loadavg)
if [ "${JUIZO_SEGUNDOS:-2400}" != "0" ] && [ "$L" -ge 4 ]; then
  say "load $L alto — encurto o slot do juízo"; JUIZO_SEGUNDOS=300
fi
export JUIZO_SEGUNDOS

# 1) avaliação determinística dos processos ainda não avaliados (ou desatualizados)
$PRIO timeout -k 60 --foreground 1200 $PY tools/processo_360.py --lote 120 --gravar \
  >> data/sweep_360_lote.out 2>&1; say "360 lote rc=$?"

# 2) juízo por documento — sobre o ACERVO INTEIRO, ordenado por risco (pedido do dono 2026-08-03:
#    "todas as perícias, 24/7, sem limitação"). Antes: fila só com pontuação >=5, 4 processos por
#    slot e teto de 25 documentos por processo — 39 de 2.082 processos julgados. Nada disso era
#    limite de máquina; a cadeia de LLM é a GRÁTIS. O que limita de verdade continua de pé: a
#    janela de tempo, o lock de escritor único e o nice/ionice.
export JFN_360_TETO_DOCS=0        # 0 = sem teto de documentos por processo
JUIZO_SEGUNDOS=${JUIZO_SEGUNDOS:-2400}
[ "$JUIZO_SEGUNDOS" = "0" ] && { say "juízo adiado neste slot"; JUIZO_PULAR=1; }
if [ -z "${JUIZO_PULAR:-}" ]; then
$PRIO timeout -k 60 --foreground $((JUIZO_SEGUNDOS + 120)) $PY - <<'PYEOF' >> data/sweep_360_llm.out 2>&1
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
# TODO o acervo entra na fila; a pontuação só decide a ORDEM (o mais grave primeiro). Cortar em
# >=5 deixava 1.686 processos sem juízo documental nenhum, para sempre.
fila = []
for r in con.execute("select * from processo_avaliacao"):
    pts, _ = pontuar(json.loads(r["achados_json"] or "[]"),
                     json.loads(r["acatamento_json"] or "{}"))
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

# O slot para por TEMPO, não por contagem: enquanto sobrar janela, segue julgando. Assim o
# acervo é coberto em passes sucessivos do cron, do mais grave para o menos, sem teto fixo.
import os, time
DEADLINE = time.monotonic() + float(os.environ.get("JUIZO_SEGUNDOS", "2400"))
feitos = 0
for _, numero in fila:
    if time.monotonic() >= DEADLINE:
        print(f"[juizo] janela esgotada — {feitos} processo(s) neste slot", flush=True)
        break
    if not tem_pendente(numero):
        continue
    restante = max(60, int(DEADLINE - time.monotonic()))
    try:
        subprocess.run([".venv/bin/python", "tools/processo_360.py", "--numero", f"SEI-{numero}",
                        "--com-llm", "--gravar"], timeout=min(600, restante))
        feitos += 1
    except subprocess.TimeoutExpired:
        print(f"[juizo] {numero}: estourou o tempo do processo — segue o lote", flush=True)
else:
    print(f"[juizo] fila varrida — {feitos} processo(s) neste slot", flush=True)
PYEOF
say "360 juizo rc=$?"
fi

# 3) fila do fiscal regravada (top do ranking por QUALIDADE do achado, não pelo score cru)
$PRIO timeout 120 $PY tools/processo_360_ranking.py --top 40 --md > data/fila_fiscal_360.md 2>>"$LOG"
say "ranking rc=$? -> data/fila_fiscal_360.md"
