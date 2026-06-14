#!/bin/bash
# sweep_dados — GRUPO endereços + benefícios + fachada (DB/rede, sem sessão itkava). LEVE: nice/ionice idle,
# bounded, SINGLE-PASS (cron repete). Escalonado FORA dos horários do SEI (sem overlap).
set -u
cd /home/jfelippebethlem/JFN || exit 1
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/sweep_dados.log
say(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

[ -f data/.pause_sweeps ] && { say "pausado (.pause_sweeps) — pulei"; exit 0; }
L=$(awk '{print int($1)}' /proc/loadavg); [ "$L" -ge 4 ] && { say "load $L alto — adia"; exit 0; }
PRIO="nice -n 10 ionice -c2 -n6"   # qualidade: best-effort, progride sem starvar
say "início (best-effort baixa prio)"
if [ -f data/.pause_endereco_sweep ]; then say "endereço pausado — pulei"; else $PRIO timeout 900 $PY -m tools.backfill_verificacao_endereco --limite 100 --pausa 0.4 >> data/endereco_serial.log 2>&1; say "endereço rc=$?"; fi
if [ -f data/.pause_beneficios_sweep ]; then say "benefícios pausado — pulei"; else $PRIO timeout 900 $PY -m tools.beneficios_sweep --limite 400 --pausa 0.3 >> data/beneficios_serial.log 2>&1; say "benefícios rc=$?"; fi
if [ -f data/.pause_fachada_sweep ]; then say "fachada pausada — pulei"; else $PRIO timeout 900 bash tools/fachada_sweep_rotativo.sh >> data/dd_sweep/cron.log 2>&1; say "fachada rc=$?"; fi
# fachada VISUAL (VLM Mapillary/satélite, GRÁTIS) — classifica os suspeitos de sede (verificacao_sede status=INDICIO),
# resumível (pula quem já tem visual_classe). --limite 0 = o quanto couber no time-bound; sweep_sede grava no MESMO DB → busy_timeout.
if [ -f data/.pause_fachada_visual_sweep ]; then say "fachada visual pausada — pulei"; else $PRIO timeout 900 $PY -m tools.fachada_visual_sweep --status INDICIO --limite 0 --max-min 14 --pausa 0.12 >> data/fachada_visual.log 2>&1; say "fachada visual rc=$?"; fi
# fachada B2 sync — guarda no Backblaze B2 a foto dos FLAGUEADOS recém-classificados (visual_classe baldio/rural/
# barraco/residencial) que ainda não têm objeto no bucket, e grava visual_img_b2. Roda APÓS o visual_sweep (que
# produz o visual_classe de que depende) = menor acoplamento. Não deixa imagem na VM (sobe e remove o temp).
# Bounded/resumível: pula quem já está no B2; degrada honesto se rclone/B2 falhar. Pausa: data/.pause_fachada_b2_sync.
if [ -f data/.pause_fachada_b2_sync ]; then say "fachada b2 pausada — pulei"; else $PRIO timeout 600 $PY -m tools.fachada_b2_sync --limite 0 --max-min 8 --pausa 0.3 >> data/fachada_b2.log 2>&1; say "fachada b2 rc=$?"; fi
say "fim"
