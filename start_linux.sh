#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# start_linux.sh — sobe o agente JFN nesta VM Linux usando o venv local.
# NÃO substitui iniciar.sh (Windows); é o ponto de entrada do alvo Linux/GCP.
#
#   ./start_linux.sh                 → sobe o servidor/agente (porta 8000)
#   ./start_linux.sh --setup         → (re)cria venv e instala TUDO (core + extras SEI)
#   ./start_linux.sh --host 0.0.0.0  → expõe na rede (cuidado: ver CLAUDE.md)
#   HOST/PORT por env: JFN_HOST, JFN_PORT
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

VENV=".venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"
export JFN_DATA_DIR="${JFN_DATA_DIR:-$PWD/data}"
HOST="${JFN_HOST:-127.0.0.1}"
PORT="${JFN_PORT:-8000}"

# permite --host/--port na linha de comando
while [ $# -gt 0 ]; do
  case "$1" in
    --setup) DO_SETUP=1; shift;;
    --host)  HOST="$2"; shift 2;;
    --port)  PORT="$2"; shift 2;;
    *) shift;;
  esac
done

if [ "${DO_SETUP:-0}" = "1" ] || [ ! -x "$PY" ]; then
  echo ">> Preparando ambiente Linux (venv + dependências)…"
  [ -d "$VENV" ] || python3 -m venv "$VENV"
  "$PIP" install --quiet --upgrade pip
  "$PIP" install --quiet -r requirements.txt
  # extras opcionais (OCR/CDP/Selenium) — só se o arquivo existir
  [ -f requirements-sei.txt ] && "$PIP" install --quiet -r requirements-sei.txt || true
  "$PY" -m playwright install chromium
  echo ">> Setup OK. (libs de sistema: tesseract-ocr tesseract-ocr-por libgl1 libglib2.0-0 libnss3 libnspr4)"
fi

[ -f .env ] || { [ -f .env.example ] && cp .env.example .env && echo ">> .env criado a partir de .env.example (preencha as chaves)"; }

echo ">> Inicializando banco…"
"$PY" -c "from compliance_agent.database.models import init_db; init_db()" || true

echo ">> Subindo JFN em http://$HOST:$PORT  (JFN_DATA_DIR=$JFN_DATA_DIR)"
exec "$PY" server.py --host "$HOST" --port "$PORT"
