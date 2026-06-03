#!/usr/bin/env bash
# ============================================================================
# setup_oracle_cloud.sh — Configura a VM Oracle Cloud para rodar o JFN Agent
# Testado em: Ubuntu 22.04 ARM64 (Oracle Always Free)
# Uso: bash setup_oracle_cloud.sh
# ============================================================================
set -e

VERDE="\033[0;32m"
AMARELO="\033[1;33m"
RESET="\033[0m"

ok()  { echo -e "${VERDE}[OK]${RESET} $*"; }
msg() { echo -e "${AMARELO}>>>  $*${RESET}"; }

msg "1/6 — Atualizando o sistema..."
sudo apt-get update -qq
sudo apt-get upgrade -y -qq
ok "Sistema atualizado."

msg "2/6 — Instalando Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    ok "Docker instalado."
else
    ok "Docker já está instalado."
fi

msg "3/6 — Instalando Docker Compose..."
sudo apt-get install -y -qq docker-compose-plugin
ok "Docker Compose instalado."

msg "4/6 — Abrindo porta 8000 no firewall do sistema..."
sudo iptables -C INPUT -p tcp --dport 8000 -j ACCEPT 2>/dev/null || \
    sudo iptables -I INPUT -p tcp --dport 8000 -j ACCEPT
sudo iptables -C INPUT -p tcp --dport 443  -j ACCEPT 2>/dev/null || \
    sudo iptables -I INPUT -p tcp --dport 443  -j ACCEPT

# Salva regras para sobreviver a reboot
if ! dpkg -l iptables-persistent &>/dev/null; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq iptables-persistent
fi
sudo netfilter-persistent save
ok "Porta 8000 liberada no iptables."

msg "5/6 — Instalando utilitários extras (git, curl, htop)..."
sudo apt-get install -y -qq git curl htop unzip
ok "Utilitários instalados."

msg "6/6 — Verificando instalação do Docker..."
docker --version
docker compose version
ok "Docker pronto!"

echo ""
echo -e "${VERDE}============================================================${RESET}"
echo -e "${VERDE} Configuração concluída!                                   ${RESET}"
echo -e "${VERDE}============================================================${RESET}"
echo ""
echo "PRÓXIMOS PASSOS:"
echo ""
echo "  1. Cole o arquivo .env nesta pasta com suas chaves de API:"
echo "     nano .env"
echo ""
echo "  2. Inicie o agente:"
echo "     docker compose up -d --build"
echo ""
echo "  3. Veja os logs em tempo real:"
echo "     docker compose logs -f"
echo ""
echo "  4. Abra no navegador:"
echo "     http://SEU-IP-DA-ORACLE:8000"
echo ""
echo "  LEMBRE: Abra a porta 8000 no console da Oracle Cloud também!"
echo "  (Networking → Virtual Cloud Networks → Security Lists → Add Ingress Rule)"
echo ""
