#!/usr/bin/env bash
# ============================================================
# Bootstrap da VM GCP (server-1, Ubuntu 24.04) — instala e sobe o Yoda/Hermes.
# Idempotente: pode rodar de novo sem quebrar. Loga tudo em ~/bootstrap.log
# ============================================================
set -uo pipefail
exec > >(tee -a "$HOME/bootstrap.log") 2>&1
echo "================ BOOTSTRAP $(date) ================"

step() { echo ""; echo ">>> $*"; }

step "[1/8] Pacotes base (python, git, ffmpeg, build)"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-venv python3-pip git ffmpeg build-essential curl ca-certificates

step "[2/8] Node.js 22 + Claude Code (plano do Mestre Jorge)"
if ! command -v node >/dev/null || [ "$(node -v | cut -dv -f2 | cut -d. -f1)" -lt 22 ]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi
node -v || true
sudo npm install -g @anthropic-ai/claude-code 2>/dev/null || echo "(claude code: instale depois se falhar)"

step "[3/8] Clona o hermes-agent (NousResearch)"
cd "$HOME"
if [ ! -d hermes-agent ]; then
    git clone --depth 1 https://github.com/NousResearch/hermes-agent.git
fi
cd "$HOME/hermes-agent"

step "[4/8] Ambiente Python + instala Hermes (messaging)"
python3 -m venv venv
./venv/bin/pip install --upgrade pip wheel
./venv/bin/pip install -e ".[messaging]" || ./venv/bin/pip install -e .

step "[5/8] Configuracao (HERMES_HOME=~/.hermes) vinda do PC"
mkdir -p "$HOME/.hermes"
if [ -d "$HOME/hermes-config" ]; then
    cp -f "$HOME/hermes-config/.env"        "$HOME/.hermes/.env"        2>/dev/null && echo ".env copiado"
    cp -f "$HOME/hermes-config/config.yaml" "$HOME/.hermes/config.yaml" 2>/dev/null && echo "config.yaml copiado"
    cp -f "$HOME/hermes-config/auth.json"   "$HOME/.hermes/auth.json"   2>/dev/null && echo "auth.json (pool Gemini) copiado"
    chmod 600 "$HOME/.hermes/.env" 2>/dev/null || true
fi

step "[6/8] Servico systemd 'yoda' (sobe sozinho e reinicia se cair)"
HERMES_DIR="$HOME/hermes-agent"
HERMES_HOME="$HOME/.hermes"
PYBIN="$HERMES_DIR/venv/bin/python"
sudo tee /etc/systemd/system/yoda.service >/dev/null <<EOF
[Unit]
Description=Yoda - Hermes Telegram Gateway
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=8

[Service]
Type=simple
User=$USER
WorkingDirectory=$HERMES_DIR
Environment=HERMES_HOME=$HERMES_HOME
Environment=PYTHONIOENCODING=utf-8
EnvironmentFile=-$HERMES_HOME/.env
ExecStart=$PYBIN -m hermes_cli.main gateway run
Restart=always
RestartSec=10
KillSignal=SIGTERM
TimeoutStopSec=210

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable yoda
sudo systemctl restart yoda

step "[7/8] Firewall local (ufw) libera 3000 (caso use)"
sudo ufw allow 3000/tcp 2>/dev/null || true

step "[8/8] Status"
sleep 5
sudo systemctl --no-pager status yoda | head -15 || true
echo ""
echo "Logs ao vivo:  journalctl -u yoda -f"
echo "================ FIM $(date) ================"
