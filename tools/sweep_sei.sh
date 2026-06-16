#!/bin/bash
# sweep_sei — GRUPO SEI (itkava/browser): sei_sweep + sei_cpf. Roda SOZINHO (sessão única livre p/ leitura
# manual entre execuções). LEVE: nice/ionice idle (só CPU/IO ocioso), bounded por timeout, SINGLE-PASS
# (o cron repete; NÃO é loop contínuo — esse era o lane ruim que segurava Chromium na memória 24h).
set -u
cd /home/ubuntu/JFN || exit 1
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/sweep_sei.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

[ -f data/.pause_sweeps ] && { say "pausado (.pause_sweeps) — pulei"; exit 0; }
[ -f data/.pause_sei_sweep ] && { say "pausado (.pause_sei_sweep) — pulei"; exit 0; }
# bracket evita auto-match; se já há um sei_sweep, NÃO abrir 2ª sessão itkava (o SEI expulsa a duplicada)
if pgrep -f 'tools\.sei_swee[p]' >/dev/null; then say "já rodando — pula"; exit 0; fi
# backstop VM-safe: se a VM já está muito carregada, adia (o cron repete no próximo slot)
L=$(awk '{print int($1)}' /proc/loadavg); [ "$L" -ge 4 ] && { say "load $L alto — adia"; exit 0; }

# ⚠ LIÇÃO §8: o server.py TAMBÉM usa ms-playwright chromium → NUNCA pkill amplo por padrão (mataria o dele).
# Mata SÓ chromium ÓRFÃO do playwright (ppid=1 = vazou de um sweep morto; o do server.py tem pai vivo).
limpa_orfaos(){ for p in $(pgrep -f 'ms-playwright/chromium' 2>/dev/null); do [ "$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')" = "1" ] && kill "$p" 2>/dev/null; done; }
limpa_orfaos

# PRIORIDADE = qualidade: best-effort de baixa prioridade (progride sempre, sem starvar como o ionice idle).
PRIO="nice -n 10 ionice -c2 -n6"
say "início (best-effort baixa prio, bounded)"
$PRIO timeout 1500 $PY -m tools.sei_sweep --max 20 >> data/sei_cache/sei_sweep_loop.out 2>&1; say "sei_sweep rc=$?"
# SEGUIR OS PROCESSOS-PAI de contratação detectados no cache (recupera a substância dos dockets de
# execução/pagamento que vêm "vazios"). Mesmo slot/sessão única itkava, DEPOIS do sweep normal; bounded;
# resumível (pais já lidos ficam em cache+progress). Lê poucos por slot (qualidade > volume na VM 2 vCPU).
$PRIO timeout 900  $PY -m tools.sei_sweep --seguir-pais --max 8 >> data/sei_cache/sei_sweep_loop.out 2>&1; say "sei_pais rc=$?"
$PRIO timeout 600  $PY -m tools.sei_cpf_sweep >> data/sei_cpf_sweep.log 2>&1; say "sei_cpf rc=$?"
# DEPURA as fichas do cache -> tabela sei_ficha (só info relevante, queryável/cruzável c/ OBs). Idempotente.
$PRIO timeout 300  $PY -m tools.sei_depurar_db >> data/sei_depurar.log 2>&1; say "sei_depurar rc=$?"
limpa_orfaos  # fecha SÓ os leftovers órfãos (não o server.py)
say "fim"
