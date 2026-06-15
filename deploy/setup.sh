#!/bin/bash
set -e

echo "=== PolitiMonitor — Setup Oracle VM Ubuntu ==="

# 1. Atualiza sistema
sudo apt-get update -y
sudo apt-get upgrade -y
sudo apt-get install -y curl git build-essential nginx certbot python3-certbot-nginx

# 2. Instala Node.js 20 via NVM
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"
nvm install 20
nvm use 20
nvm alias default 20

# 3. PM2 global
npm install -g pm2

# 4. Clona o repo (ajuste a URL)
cd ~/
git clone https://github.com/jfelippebethlem-tech/jfn.git JFN || true
cd JFN
git checkout claude/polimonitor-app-ZClUe

# 5. Copia e edita o .env
if [ ! -f .env ]; then
  cp .env.example .env 2>/dev/null || cat > .env << 'EOF'
DATABASE_URL="file:./dev.db"
AUTH_SECRET="TROQUE_POR_SEGREDO_FORTE_AQUI"
ADMIN_PASSWORD="TROQUE_POR_SENHA_FORTE_AQUI"
GEMINI_API_KEY=""
OPENROUTER_API_KEY=""
FACEBOOK_PAGE_TOKEN=""
TWITTER_BEARER_TOKEN=""
TWITTER_USERNAME=""
TELEGRAM_BOT_TOKEN=""
EOF
  echo ">>> IMPORTANTE: edite o arquivo .env antes de continuar!"
fi

# 6. Instala dependências e faz build
npm ci
npm run build

# 7. Configura PM2 ecosystem
cp deploy/ecosystem.config.js ./ecosystem.config.js

# 8. Inicia com PM2
pm2 start ecosystem.config.js
pm2 save
pm2 startup | tail -1 | sudo bash

# 9. Copia config Nginx
sudo cp deploy/nginx.conf /etc/nginx/sites-available/politimonitor
sudo ln -sf /etc/nginx/sites-available/politimonitor /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

echo ""
echo "=== Setup concluído! ==="
echo "App rodando em http://$(curl -s ifconfig.me)"
echo "Para HTTPS: sudo certbot --nginx -d seudominio.com"
echo "Para ver logs: pm2 logs"
echo "Para atualizar: bash ~/JFN/deploy/update.sh"
