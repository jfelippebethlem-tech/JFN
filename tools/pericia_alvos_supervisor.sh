#!/bin/bash
# pericia_alvos_supervisor — perícia de Due Diligence (fachada/laranja nos fornecedores PJ) nos ALVOS
# prioritários pedidos pelo dono, NA ORDEM: bombeiros -> IRM/INDUCTA -> TJRJ -> fundos.
# Só orquestra ferramentas JÁ existentes (tools.dd_sweep_orgao); NÃO altera código do núcleo/Fable.
# Browser-free (geocode=False, Gemini off) -> não conflita com o sweep SEI. Resumível (checkpoint por CNPJ).
# VM-safe: 1 UG por vez, cede se a carga estourar. Pausa: criar data/.pause_pericia_alvos.
cd /home/ubuntu/JFN || exit 1
echo $$ > data/pericia_alvos.pid
LOG=data/pericia_alvos.log
PY=".venv/bin/python"; export PYTHONPATH=.
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

# UG:rótulo na ORDEM de prioridade do dono
ALVOS=(
  "166100:bombeiros(FUNESBOM)"
  "216500:IRM/INDUCTA(CasaCivil)"
  "036100:TJRJ(FETJ)"
  "296100:fundo-saude"
  "266500:fundo-PM"
  "316100:fundo-transportes"
)

say "pericia_alvos_supervisor iniciado — ${#ALVOS[@]} alvos, ordem do dono"
for item in "${ALVOS[@]}"; do
  ug="${item%%:*}"; lbl="${item##*:}"
  # pausa manual
  while [ -f data/.pause_pericia_alvos ]; do say "PAUSA (flag) — aguardando"; sleep 120; done
  # VM-safe: espera se a carga de 1min > 2.5 (VM 2-core)
  while :; do
    l=$(awk '{print $1}' /proc/loadavg)
    if awk -v l="$l" 'BEGIN{exit !(l>2.5)}'; then say "carga alta ($l) — aguardando 90s antes de $lbl"; sleep 90; else break; fi
  done
  say ">>> UG $ug ($lbl): iniciando dd_sweep (cauda fachada-prone primeiro)"
  $PY -m tools.dd_sweep_orgao "$ug" --ordem asc >> data/pericia_alvos.out 2>&1
  say "<<< UG $ug ($lbl): dd_sweep rc=$? — relatório em data/dd_sweep/dd_sweep_${ug}.md"
done
say "pericia_alvos_supervisor CONCLUIU todos os alvos"
