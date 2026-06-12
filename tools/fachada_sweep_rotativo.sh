#!/bin/bash
# fachada_sweep_rotativo — sweep de FACHADA (dd_sweep_orgao) escalonado, 1 UG por execução.
# Roda a DD estrutural na CAUDA (valor baixo = perfil fachada) das UGs com mais fornecedores, pulando as já
# varridas nos últimos 7 dias. Educado (cache TTL + rate-limiter, sem geocode) e VM-safe (load guard).
# Cron sugerido (escalonado, depois do endereço 10h): 0 16 * * * … fachada_sweep_rotativo.sh
set -u
cd /home/jfelippebethlem/JFN || exit 1
OUT=data/dd_sweep; mkdir -p "$OUT"
[ -f data/.pause_fachada_sweep ] && { echo "pausado"; exit 0; }
# guard de carga (não competir com SEI+endereço sob pressão)
L=$(awk '{print int($1)}' /proc/loadavg); [ "$L" -ge 3 ] && { echo "load $L alto — pula"; exit 0; }

# UGs alvo por volume de fornecedores (cauda = onde mora fachada). Ordem de prioridade.
UGS="010100 016100 036100 030100 290100 170100 200100 180100 240100 250100 320100 130100 160100 403200"
for ug in $UGS; do
  f="$OUT/dd_sweep_${ug}.jsonl"
  # pula se varrida nos últimos 7 dias
  if [ -f "$f" ] && [ "$(find "$f" -mtime -7 2>/dev/null)" ]; then continue; fi
  echo "[fachada_rotativo] varrendo UG $ug (cauda ≤ R\$100k, limite 500)…"
  .venv/bin/python -m tools.dd_sweep_orgao "$ug" --ordem asc --max-valor 100000 --limite 500 --pausa 0.3 \
    >> "$OUT/run_${ug}.log" 2>&1
  echo "[fachada_rotativo] UG $ug concluída → $OUT/dd_sweep_${ug}.md"
  exit 0   # uma UG por execução (VM-safe, escalonado)
done
echo "[fachada_rotativo] todas as UGs prioritárias varridas nos últimos 7 dias — nada a fazer."
