#!/bin/bash
# Redo de fachada via Google Street View Static (value-first, resumível, só flagradas guardam foto).
cd /home/ubuntu/JFN || exit 1
exec 9>/home/ubuntu/JFN/data/.lock_fachada_sv
flock -n 9 || { echo "[fachada_sv] já rodando — saindo"; exit 0; }
set -a; . /home/ubuntu/JFN/.env 2>/dev/null; set +a
export STREETVIEW_KEY="${GOOGLE_MAPS_KEY}"
/home/ubuntu/JFN/.venv/bin/python -m? 2>/dev/null
/home/ubuntu/JFN/.venv/bin/python tools/fachada_visual_sweep.py --todos --limite 0 --max-min 25 --workers 3 --load-teto 4.0
