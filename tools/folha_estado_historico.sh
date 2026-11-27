#!/usr/bin/env bash
# Disparo da VM-1 contra o it-campo: histórico da folha do Estado (GESPERJ) desde 2020, no máximo 6 competências por
# execução (retoma pelos marcadores ok_). Ver tools/folha_estado_historico.py.
set -euo pipefail
timeout 21000 ssh it-campo 'wsl -d Ubuntu -- bash -c "cd ~/JFN-worker && nice -n 10 .venv/bin/python -m tools.folha_estado_historico ~/folhas --max 6 --paralelo 3"'
