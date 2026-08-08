#!/bin/bash
# Leitura DIRIGIDA dos autos do caso FSERJ (dirigentes sócios de contratadas — vault:
# casos/fserj-dirigentes-socios-de-contratadas). Os 5 processos MEDVIVA têm só captura rasa
# (CDP, excerto de 400 chars); para achar QUEM ATESTA/AUTORIZA é preciso o teor integral.
# Roda com o sweep PAUSADO (sessão itkava é única — duas capturas e o SEI expulsa a duplicada).
set -u
cd /home/ubuntu/JFN || exit 1
[ -f .env ] && { set -a; . ./.env; set +a; }
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/ler_medviva.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

touch data/.pause_sei_sweep
say "início — sweep pausado"
trap 'rm -f data/.pause_sei_sweep; say "flag de pausa removida"' EXIT

for P in "080002/014914/2024" "080002/011699/2024" "080002/019714/2024" \
         "080002/020069/2024" "080002/018759/2025" "080002/017280/2024"; do
  TAG=$(echo "$P" | tr '/' '_')
  say "lendo $P (integral, resiliente)…"
  SEI_MAX_DOCS=200 timeout -k 120 --foreground 1800 \
    $PY tools/sei_processo_integral.py "$P" "data/proc_integra/SEI_${TAG}.pdf" \
    >> "$LOG" 2>&1
  say "processo $P rc=$?"
done
# materializa no arquivo compacto pelo caminho canônico (nunca reimplementar)
for P in "SEI-080002/014914/2024" "SEI-080002/011699/2024" "SEI-080002/019714/2024" \
         "SEI-080002/020069/2024" "SEI-080002/018759/2025" "SEI-080002/017280/2024"; do
  timeout 600 $PY -m tools.sei_arquivar_do_cache --aplicar --max 1 --so "$P" >> "$LOG" 2>&1
  say "arquivar $P rc=$?"
done
say "fim"
