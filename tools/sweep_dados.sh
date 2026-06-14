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
# fachada STREET VIEW (Google Maps Embed API, GRÁTIS/ilimitada) — SUBSTITUI o par Mapillary
# (fachada_visual_sweep + fachada_b2_sync, ambos APOSENTADOS em 2026-06-14: cobertura ruim, fotos efêmeras).
# Um único sweep faz tudo por suspeito (verificacao_sede status=INDICIO, maior R$ primeiro): RENDERIZA o
# Street View Embed (iframe + HTTP local, VM-safe: subprocesso com cap de RAM real do cgroup + timeout + gate
# mem/load — UM render por vez), VALIDA (rejeita branca), SOBE p/ R2→B2 (grava visual_img_b2), RECLASSIFICA
# com o VLM (visual_fonte=street_view_embed) e CRUZA foto×Google (coerencia_google). Resumível (pula quem já
# tem a foto SV) + dedup por prédio. Render é mais pesado → time-bound conservador e pausa entre alvos.
# Pausa: data/.pause_fachada_streetview_sweep. (Os flags antigos .pause_fachada_visual_sweep/.pause_fachada_b2_sync
# ficam só como freio dos sweeps Mapillary aposentados, que saíram do caminho ativo.)
if [ -f data/.pause_fachada_streetview_sweep ]; then say "fachada street view pausada — pulei"; else $PRIO timeout 1500 $PY -m tools.fachada_streetview_sweep --status INDICIO --limite 0 --max-min 22 --pausa 1.0 >> data/fachada_streetview.log 2>&1; say "fachada street view rc=$?"; fi
say "fim"
