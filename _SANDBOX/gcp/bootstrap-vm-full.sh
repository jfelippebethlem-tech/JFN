#!/usr/bin/env bash
# ==============================================================
# INSTALADOR COMPLETO da VM GCP — deixa TODO o repo rodando 24h:
#   Yoda/Hermes (Telegram) + JFN (SEI/SIAFE/DOERJ) + Chromium p/ automacao
#   + ponte /claude no Telegram (Claude Code headless).
# Idempotente: pode rodar de novo. Loga em ~/bootstrap-full.log
# ==============================================================
set -uo pipefail
exec > >(tee -a "$HOME/bootstrap-full.log") 2>&1
echo "================ INSTALADOR COMPLETO $(date) ================"
step(){ echo ""; echo ">>> $*"; }

step "[1] Pacotes base + Chromium + display virtual (p/ automacao web)"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-venv python3-pip git ffmpeg build-essential curl ca-certificates unzip \
    chromium-browser chromium-chromedriver xvfb fonts-liberation libnss3 libgbm1 libasound2 \
    2>/dev/null || \
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-venv python3-pip git ffmpeg build-essential curl ca-certificates unzip \
    chromium chromium-driver xvfb fonts-liberation libnss3 libgbm1
echo "chromium: $(command -v chromium-browser || command -v chromium || echo 'ver snap')"

step "[2] Node.js 22 + Claude Code (para o comando /claude)"
if ! command -v node >/dev/null || [ "$(node -v 2>/dev/null | sed 's/v//;s/\..*//')" -lt 22 ] 2>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi
sudo npm install -g @anthropic-ai/claude-code 2>/dev/null || echo "(claude code: revisar depois)"
node -v; echo "claude: $(command -v claude || echo 'instalar/logar depois')"

step "[3] Hermes (Yoda) — clona e instala"
cd "$HOME"
[ -d hermes-agent ] || git clone --depth 1 https://github.com/NousResearch/hermes-agent.git
cd "$HOME/hermes-agent"
python3 -m venv venv
./venv/bin/pip install --upgrade pip wheel
./venv/bin/pip install -e ".[messaging]" || ./venv/bin/pip install -e .

step "[4] JFN — clona (SEI/SIAFE/DOERJ) e instala dependencias"
cd "$HOME"
if [ ! -d JFN ]; then
    # usa o token do .env se existir (repo pode ser privado)
    if [ -f "$HOME/.hermes/.env" ] && grep -q '^GITHUB_TOKEN=' "$HOME/.hermes/.env"; then
        GT=$(grep '^GITHUB_TOKEN=' "$HOME/.hermes/.env" | cut -d= -f2-)
        git clone "https://${GT}@github.com/jfelippebethlem-tech/JFN.git" JFN || \
        git clone https://github.com/jfelippebethlem-tech/JFN.git JFN || echo "(JFN: clone manual depois)"
    else
        git clone https://github.com/jfelippebethlem-tech/JFN.git JFN || echo "(JFN: repo privado, configurar token)"
    fi
fi
if [ -d "$HOME/JFN" ]; then
    cd "$HOME/JFN"
    python3 -m venv venv 2>/dev/null || true
    ./venv/bin/pip install --upgrade pip wheel 2>/dev/null || true
    [ -f requirements.txt ] && ./venv/bin/pip install -r requirements.txt
    [ -f pyproject.toml ] && ./venv/bin/pip install -e . 2>/dev/null || true
    # deps comuns dos modulos
    ./venv/bin/pip install requests oci playwright beautifulsoup4 lxml websocket-client python-dotenv 2>/dev/null || true
    ./venv/bin/python -m playwright install chromium 2>/dev/null || true
fi

step "[5] Configuracao do Hermes (vinda do PC, ja enviada em ~/hermes-config)"
mkdir -p "$HOME/.hermes"
for f in .env config.yaml auth.json; do
    [ -f "$HOME/hermes-config/$f" ] && cp -f "$HOME/hermes-config/$f" "$HOME/.hermes/$f" && echo "$f ok"
done
chmod 600 "$HOME/.hermes/.env" 2>/dev/null || true

step "[6] Servico systemd 'yoda' (Telegram 24h, reinicia sozinho)"
PYBIN="$HOME/hermes-agent/venv/bin/python"
sudo tee /etc/systemd/system/yoda.service >/dev/null <<EOF
[Unit]
Description=Yoda - Hermes Telegram Gateway
After=network-online.target
Wants=network-online.target
# guarda anti restart-storm (se falhar 8x em 5min, para de tentar)
StartLimitIntervalSec=300
StartLimitBurst=8
[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME/hermes-agent
Environment=HERMES_HOME=$HOME/.hermes
Environment=PYTHONIOENCODING=utf-8
Environment=DISPLAY=:99
# carrega o .env explicitamente (- = opcional, nao quebra se sumir)
EnvironmentFile=-$HOME/.hermes/.env
ExecStartPre=/bin/bash -c 'Xvfb :99 -screen 0 1280x800x24 >/dev/null 2>&1 &'
ExecStart=$PYBIN -m hermes_cli.main gateway run
Restart=always
RestartSec=10
KillSignal=SIGTERM
# >= drain_timeout (180s) p/ o systemd nao matar no meio do encerramento limpo
TimeoutStopSec=210
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable yoda
sudo systemctl restart yoda

step "[7] Ponte /claude (Telegram -> claude -p headless)"
# instalada por arquivo separado claude-bridge.py + servico, se presente
if [ -f "$HOME/hermes-config/claude_bridge.py" ]; then
    cp -f "$HOME/hermes-config/claude_bridge.py" "$HOME/claude_bridge.py"
    echo "claude_bridge.py copiado (configurar token/servico na proxima etapa)"
fi

step "[8] Status final"
sleep 5
sudo systemctl --no-pager status yoda | head -12 || true
echo ""
echo "Yoda logs:  journalctl -u yoda -f"
echo "================ FIM $(date) ================"
