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
echo ""
echo "  2. Calibre o modelo com dados históricos (recomendado, ~20–40 min):"
echo "       cd stock_agent"
echo "       python agent.py --backtest"
echo "     Ou versão rápida (20 tickers):"
echo "       python agent.py --backtest --quick"
echo ""
echo "  3. Teste o envio de mensagens (QR Code na 1ª vez):"
echo "       python agent.py --test"
echo ""
echo "  4. Modo live (roda automaticamente seg–sex 10h–17h):"
echo "       python agent.py"
echo ""
echo "  Outros comandos úteis:"
echo "       python agent.py --ticker WEGE3   # análise de ticker único"
echo "       python agent.py --stats          # performance dos sinais enviados"
echo "       python agent.py --learn          # reatualiza pesos de aprendizado"
