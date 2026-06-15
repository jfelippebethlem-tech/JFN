#!/bin/bash
set -e

echo "=== Atualizando PolitiMonitor ==="
cd ~/JFN

git fetch origin
git pull origin claude/polimonitor-app-ZClUe

npm ci
npx prisma migrate deploy
npm run build

mkdir -p /var/log/politimonitor
pm2 reload ecosystem.config.js --update-env

echo "=== Atualização concluída! ==="
pm2 status
