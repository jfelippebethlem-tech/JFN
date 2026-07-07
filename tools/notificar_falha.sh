#!/bin/bash
# notificar_falha — handler genérico do OnFailure= das unidades systemd do ecossistema.
# Uso: notificar_falha.sh <unidade>  (o template notificar-falha@.service passa %i)
set -u
cd /home/ubuntu/JFN || exit 1
set -a; . .env; set +a
UNIT="${1:-desconhecida}" PYTHONPATH=. exec .venv/bin/python - <<'PY'
import os
from tools.ronda import notificar
u = os.environ.get("UNIT", "desconhecida")
notificar(f"🔴 <b>systemd</b>: unidade <b>{u}</b> FALHOU — <code>journalctl --user -u {u} -n 30</code>")
PY
