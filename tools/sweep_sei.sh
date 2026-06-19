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
# LEITURA COMPLETA = padrão (ler() canônico: TODOS os docs + OCR de scan, WAF-safe + cracked). ~3x mais pesada/processo
# → batch menor p/ caber no timeout e não saturar os 2 vCPU (cron repete; cobre a fila ao longo dos runs).
$PRIO timeout 1500 $PY -m tools.sei_sweep --max 12 >> data/sei_cache/sei_sweep_loop.out 2>&1; say "sei_sweep rc=$?"
# FOCO: UGs sob teste/observação (data/ugs_foco.txt) — lê os processos SEI dessas UGs por valor.
# Mesma sessão única itkava (sequencial, DEPOIS do sweep geral); bounded; resumível.
if [ -f data/ugs_foco.txt ]; then
  while read -r ugcod _resto; do
    case "$ugcod" in ''|\#*) continue;; esac
    $PRIO timeout 700 $PY -m tools.sei_sweep --ug "$ugcod" --max 6 >> data/sei_cache/sei_sweep_loop.out 2>&1; say "sei_foco ug=$ugcod rc=$?"
  done < data/ugs_foco.txt
fi
# SEGUIR OS PROCESSOS-PAI de contratação detectados no cache (recupera a substância dos dockets de
# execução/pagamento que vêm "vazios"). Mesmo slot/sessão única itkava, DEPOIS do sweep normal; bounded;
# resumível (pais já lidos ficam em cache+progress). Lê poucos por slot (qualidade > volume na VM 2 vCPU).
$PRIO timeout 900  $PY -m tools.sei_sweep --seguir-pais --max 5 >> data/sei_cache/sei_sweep_loop.out 2>&1; say "sei_pais rc=$?"
$PRIO timeout 600  $PY -m tools.sei_cpf_sweep >> data/sei_cpf_sweep.log 2>&1; say "sei_cpf rc=$?"
# RE-FICHA bounded: re-extrai a ficha de quem ainda NÃO tem o campo `situacao` (idempotente — pula quem já
# tem). Auto-cura a cobertura ao longo dos dias quando o nous tem janelas boas (sem pendência manual). Bounded.
$PRIO timeout 600  $PY -m tools.sei_refichar --max 40 >> data/sei_refichar.log 2>&1; say "sei_refichar rc=$?"
# DEPURA as fichas do cache -> tabela sei_ficha (só info relevante, queryável/cruzável c/ OBs). Idempotente.
$PRIO timeout 300  $PY -m tools.sei_depurar_db >> data/sei_depurar.log 2>&1; say "sei_depurar rc=$?"
# CONSOLIDA cada árvore de processo num dossiê TXT (data/sei_trees/) + tabela sei_arvore — o que o Lex lê.
$PRIO timeout 400  $PY -m tools.sei_arvore_build >> data/sei_arvore.log 2>&1; say "sei_arvore rc=$?"
# MEMÓRIA cruzada de direcionamento por fornecedor (acumula; barato, sem LLM em massa; ente público zerado).
$PRIO timeout 200  $PY -m tools.sei_direcionamento_varre >> data/sei_direc.log 2>&1; say "sei_direc rc=$?"
# DIRECIONAMENTO on-demand: o cérebro caro (gemini, tier PRODUTO) SÓ nos TOP-SCORE — poucos por slot, NÃO é
# volume; cache de 30d faz a maioria dos slots não reavaliar nada. Surface no Lex/relatorio (§II-F). Bounded.
$PRIO timeout 400  $PY -m tools.sei_direcionamento_llm --top 6 >> data/sei_direc.log 2>&1; say "sei_direc_llm rc=$?"
# PESQUISA-INTERNET (Fase 5): o Lex pesquisa as dúvidas dos TOP-SCORE (OSINT/web/DOERJ/mídia adversa),
# aprende (vault + DB lex_pesquisa) e re-ajusta a análise. Poucos por slot (rede + LLM produto); cache 30d.
$PRIO timeout 600  $PY -m tools.lex_pesquisa_internet --top 3 >> data/lex_pesquisa.log 2>&1; say "lex_pesquisa rc=$?"
# EXECUÇÃO DO CONTRATO (Gemini): o Lex avalia se a entrega foi comprovada e COERENTE com o objeto/
# quantidade (prestação de contas, fiscalização/relatório fotográfico, plausibilidade física). Poucos/slot.
$PRIO timeout 600  $PY -m tools.lex_execucao --top 4 >> data/lex_execucao.log 2>&1; say "lex_execucao rc=$?"
# FEEDBACK Lex/JFN → Claude Code (determinístico, sem LLM): consolida dificuldades/ideias do ciclo na nota do vault.
$PRIO timeout 120  env PYTHONPATH=. $PY -m tools.lex_feedback --auto >> data/lex_feedback.log 2>&1; say "lex_feedback rc=$?"
limpa_orfaos  # fecha SÓ os leftovers órfãos (não o server.py)
say "fim"
