#!/usr/bin/env bash
# Ponte das sessões do Claude NA NUVEM (claude.ai/code) para as nossas máquinas pelo Tailscale — SEM login manual e SEM
# deixar nó para trás (27/11/2026: 13 nós «claude-*» offline, sem tag e sem efêmero; cada sessão pedia rede nova).
#
# Requisito (uma vez, pelo dono, no painel do Tailscale): chave de autenticação REUTILIZÁVEL + EFÊMERA + PRÉ-APROVADA
# com a tag `tag:claude-cloud`, guardada no ambiente do claude.ai/code como variável TS_AUTHKEY (nunca no repositório).
# Uso no «setup script» do ambiente: baixar este arquivo para ponte.sh (curl -fsSL <raw> -o ponte.sh) e rodar bash ponte.sh
# Idempotente: se já estiver conectado, só confere.
set -euo pipefail
: "${TS_AUTHKEY:?defina TS_AUTHKEY (chave efêmera/reutilizável/tag:claude-cloud) nas variáveis do ambiente}"
NOME="${TS_NOME:-claude-cloud}"
SOCKS=localhost:1055

if ! command -v tailscale >/dev/null 2>&1; then
  # baixa para ARQUIVO e só então executa (regra da casa: nada de baixar-e-executar às cegas por pipe)
  curl -fsSL https://tailscale.com/install.sh -o /tmp/tailscale-install.sh
  sh /tmp/tailscale-install.sh >/dev/null
fi
# a nuvem não tem /dev/net/tun: modo userspace + proxy SOCKS5 para ssh/http chegarem às máquinas
if ! pgrep -x tailscaled >/dev/null 2>&1; then
  (sudo -n true 2>/dev/null && SUDO=sudo || SUDO="")
  ${SUDO:-} nohup tailscaled --tun=userspace-networking --socks5-server="$SOCKS" --outbound-http-proxy-listen="$SOCKS" \
    --state=mem: >/tmp/tailscaled.log 2>&1 &
  sleep 3
fi
# TS_AUTHKEY pode ser (a) chave comum (tskey-auth-…, validade máx. 90 dias) ou (b) SEGREDO DE CLIENTE OAuth
# (tskey-client-…, não expira; 27/11/2026): com (b) o nó é criado na hora, efêmero e com a tag
if [[ "$TS_AUTHKEY" == tskey-client-* ]]; then
  CHAVE="${TS_AUTHKEY}?ephemeral=true&preauthorized=true"; TAGS="--advertise-tags=tag:claude-cloud"
else
  CHAVE="$TS_AUTHKEY"; TAGS=""
fi
tailscale status >/dev/null 2>&1 || tailscale up --authkey="$CHAVE" $TAGS --hostname="$NOME" --accept-dns=false
# ssh pelo nome (MagicDNS resolvido pelo próprio tailscale), nunca por IP
mkdir -p ~/.ssh && chmod 700 ~/.ssh
if ! grep -q "# ponte-tailscale" ~/.ssh/config 2>/dev/null; then
  cat >> ~/.ssh/config <<'EOF'
# ponte-tailscale (sessão na nuvem → máquinas do dono). A nuvem NÃO guarda chave: entra só no NÓ-PONTE da VM-1 (jfn-ponte, tag:jfn; tools/nuvem/no_ponte_vm1.sh) pelo Tailscale SSH
# (autenticação pela identidade do nó + regra de acesso da tag:claude-cloud); VM-2 e it-campo pelas chaves da VM-1:
#   ssh vm1 'ssh vm2-ts <comando>'    |    ssh vm1 'ssh it-campo <comando>'
Host vm1 jfn-ponte
  HostName jfn-ponte
  User ubuntu
  ProxyCommand tailscale nc %h %p
  StrictHostKeyChecking accept-new
EOF
  chmod 600 ~/.ssh/config
fi
export ALL_PROXY="socks5h://$SOCKS"
tailscale status --peers=false 2>/dev/null | head -1
for h in jfn-ponte jfn-agent-2 jorge; do          # VM-1, VM-2, it-campo («jorge» na rede)
  if timeout 8 tailscale ping -c 1 "$h" >/dev/null 2>&1; then echo "ok  $h"; else echo "SEM RESPOSTA  $h"; fi
done
echo "ponte pronta: ssh vm1 · ssh vm1 'ssh vm2-ts …' · ssh vm1 'ssh it-campo …'   (HTTP: ALL_PROXY=socks5h://$SOCKS)"
