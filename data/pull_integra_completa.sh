#!/bin/bash
# Íntegra COMPLETA (toda a instrução + índice clicável por documento) dos processos-chave, via
# sei_processo_integral (usa ler() canônico, abre cross-unit, extrai conteúdo). Serializado, resumível.
set -u
cd /home/ubuntu/JFN || exit 1
export PYTHONPATH=. SEI_MAX_DOCS=500 SEI_DOC_TIMEOUT=14
PY=.venv/bin/python
LOG=data/pull_integra.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
livre(){ for _ in $(seq 1 90); do pgrep -f "sei_sweep|siafe_ob_orcamentaria|siafe_runner" >/dev/null 2>&1 && sleep 30 || return 0; done; }
PROCS=(
  "070026/000705/2021|AmbienteJovem-contrato-gestao-001-2021"
  "070002/004135/2025|Lytoranea-macrodrenagem-Maxambomba-R96mi"
  "070002/000991/2022|Lytoranea-macrodrenagem-R70mi"
  "070002/015404/2022|Das-Dragmaq-desassoreamento-R41mi"
  "070002/012954/2022|Hydra-urbanizacao-R52mi"
  "070002/001289/2022|Metropolitana-macrodrenagem"
  "07/0028/000089/2021|Brasform-UEPSAM-R40mi"
  "070026/000410/2021|Trial-SEAS-R6mi"
)
mkdir -p data/proc_integra
say "=== PULL ÍNTEGRA (via ler): início (${#PROCS[@]}) ==="
for item in "${PROCS[@]}"; do
  proc="${item%%|*}"; rot="${item##*|}"
  [ -f "data/proc_integra/${rot}.pdf" ] && { say "já feito: $rot"; continue; }
  livre; pkill -9 -f ms-playwright 2>/dev/null; sleep 2
  say "lendo $proc ($rot)"
  timeout 3000 $PY tools/sei_processo_integral.py "$proc" "data/proc_integra/${rot}.pdf" >> "$LOG" 2>&1
  [ -f "data/proc_integra/${rot}.pdf" ] && say "  OK $rot" || say "  FALHOU $rot"
  sleep 5
done
say "=== FIM ==="
$PY - <<'PY' >> "$LOG" 2>&1
import os,re,asyncio,glob,fitz
for ln in open('.env',encoding='utf-8',errors='replace'):
    m=re.match(r'^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$',ln)
    if m: os.environ.setdefault(m.group(1),m.group(2).strip().strip('"').strip("'"))
os.environ["TELEGRAM_CHAT_ID"]=os.environ.get("TELEGRAM_OWNER_ID","")
from compliance_agent.notifications.telegram import enviar_mensagem
fs=sorted(glob.glob("data/proc_integra/*.pdf"))
tot=sum(len(fitz.open(f).get_toc()) for f in fs)
msg=f"🗂️ *Íntegra dos processos administrativos pronta:* {len(fs)} processos, ~{tot} documentos indexados (índice clicável por doc).\n"+"\n".join("• "+os.path.basename(p).replace('.pdf','') for p in fs)+"\nMontando Anexo D no dossiê-mestre."
asyncio.run(enviar_mensagem(msg, chat_id=os.environ.get("TELEGRAM_OWNER_ID","")))
PY
