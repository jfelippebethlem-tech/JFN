#!/usr/bin/env bash
# JFN Stock Agent — setup script
set -euo pipefail

echo "=== JFN Stock Agent Setup ==="

# --- Python dependencies ---
echo "[1/3] Instalando dependências Python..."
cd "$(dirname "$0")/stock_agent"
pip install -r requirements.txt --quiet

# --- Node.js dependencies ---
echo "[2/3] Instalando dependências Node.js (whatsapp-web.js)..."
cd ../whatsapp
npm install --silent

# --- .env ---
cd ..
echo "[3/3] Configurando .env..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "  ✓ Arquivo .env criado. Edite-o com seu número:"
    echo "    WHATSAPP_PHONE=5511999999999"
else
    echo "  .env já existe (não sobrescrito)."
fi

echo ""
echo "=== Configuração concluída! ==="
echo ""
echo "Próximos passos:"
echo "  1. Edite .env com seu número de WhatsApp"
echo "  2. Execute o agente:"
echo "       cd stock_agent && python agent.py --test"
echo ""
echo "  Na primeira execução, um QR Code aparecerá no terminal."
echo "  Escaneie com o WhatsApp do seu celular (uma única vez)."
echo ""
echo "  Para rodar em modo live (durante o pregão, seg–sex 10h–17h):"
echo "       python agent.py"
echo ""
echo "  Para analisar uma ação específica:"
echo "       python agent.py --ticker WEGE3"
