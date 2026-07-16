#!/bin/bash
# Puxa (íntegra) os PROCESSOS SEI dos grandes contratos de SEAS/INEA da gestão Pampolha + tenta o
# processo do acordo CEDAE/Águas do Rio. Cross-unit (070002 INEA, 070026 SEAS): o leitor pode não abrir
# (degrada honesto). Serializado (1 browser por vez), bounded, reporta no Telegram. SEI_SEM_TG=1 = só baixa.
set -u
cd /home/ubuntu/JFN || exit 1
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/pull_seas_inea.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
livre(){ for _ in $(seq 1 120); do pgrep -f "sei_sweep|sei_integra_completa|siafe_ob_orcamentaria|siafe_runner" >/dev/null 2>&1 && sleep 30 || return 0; done; }

# processos dos maiores contratos (dedup); rótulo p/ o log
PROCS=(
  "070002/004135/2025|Lytoranea-macrodrenagem-Maxambomba-R96mi"
  "070002/000991/2022|Lytoranea-macrodrenagem-R70mi"
  "070002/015404/2022|Das-Dragmaq-desassoreamento-R41mi"
  "070002/012954/2022|Hydra-urbanizacao-R52mi"
  "070002/001289/2022|Metropolitana-macrodrenagem"
  "07/0028/000089/2021|Brasform-UEPSAM-R40mi"
  "070026/000410/2021|Trial-SEAS-R6mi"
)
say "=== PULL processos SEAS/INEA: início (${#PROCS[@]} processos) ==="
mkdir -p data/proc_seas_inea
for item in "${PROCS[@]}"; do
  proc="${item%%|*}"; rot="${item##*|}"
  livre
  say "lendo $proc ($rot)"
  SEI_SEM_TG=1 SEI_MAX_PAG=250 timeout 900 $PY tools/sei_integra_completa.py "$proc" >> "$LOG" 2>&1
  tag=$(echo "$proc" | tr -c '0-9' '_')
  if [ -f "data/sei_cache/INTEGRA_${tag}.pdf" ]; then
    cp "data/sei_cache/INTEGRA_${tag}.pdf" "data/proc_seas_inea/${rot}.pdf" 2>/dev/null
    say "  OK $proc -> ${rot}.pdf"
  else
    say "  SEM ÁRVORE/vazio $proc (cross-unit: leitor não abriu)"
  fi
  sleep 8
done
say "=== PULL processos SEAS/INEA: FIM ==="

# resumo no Telegram
$PY - <<'PY' >> "$LOG" 2>&1
import os, re, asyncio, glob
for ln in open('.env',encoding='utf-8',errors='replace'):
    m=re.match(r'^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$',ln)
    if m: os.environ.setdefault(m.group(1),m.group(2).strip().strip('"').strip("'"))
os.environ["TELEGRAM_CHAT_ID"]=os.environ.get("TELEGRAM_OWNER_ID","")
from compliance_agent.notifications.telegram import enviar_mensagem
lidos=glob.glob("data/proc_seas_inea/*.pdf")
msg=("🗂️ *Pull dos processos SEI de SEAS/INEA (gestão Pampolha)* concluído.\n"
     f"Lidos com árvore: {len(lidos)} de 7.\n"
     + ("\n".join("• "+os.path.basename(p).replace('.pdf','') for p in lidos) if lidos else "Nenhum abriu (processos de outra unidade — 070002/INEA; o leitor itkava/ITERJ não abre cross-unit).")
     + "\nOs números dos contratos e objetos já estão no dossiê (seção 11); a análise jurídica de improbidade segue com base neles.")
asyncio.run(enviar_mensagem(msg, chat_id=os.environ.get("TELEGRAM_OWNER_ID","")))
PY
