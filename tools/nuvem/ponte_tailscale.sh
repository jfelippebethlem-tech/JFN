#!/usr/bin/env bash
# Ponte das sessões do Claude NA NUVEM (claude.ai/code) para as nossas máquinas pelo Tailscale — SEM login manual e SEM
# deixar nó para trás (27/11/2026: 13 nós «claude-*» offline, sem tag e sem efêmero; cada sessão pedia rede nova).
#
# DUAS FASES (medido 27/11 numa sessão real do ambiente Default):
#   1) SETUP SCRIPT do ambiente (roda ANTES do Claude Code e o resultado fica EM CACHE; NÃO enxerga as variáveis do
#      ambiente; nenhum processo sobrevive ao cache):  bash ponte.sh instalar
#      → instala tailscale + ssh, copia este arquivo para ~/.local/bin/ponte-tailscale e registra um gancho SessionStart
#        no ~/.claude/settings.json do container.
#   2) Cada SESSÃO: o gancho roda `ponte-tailscale conectar` em segundo plano (aí TS_AUTHKEY existe).
# TS_AUTHKEY (variável do ambiente no claude.ai/code, nunca no repositório): segredo de cliente OAuth (tskey-client-…,
# não expira; só Auth Keys write + tag:claude-cloud) ou chave comum (tskey-auth-…, máx. 90 dias).
# Rede do ambiente: Limited com tailscale.com, *.tailscale.com, raw.githubusercontent.com + gerenciadores de pacote.
set -euo pipefail
NOME="${TS_NOME:-claude-cloud}"
SOCKS=localhost:1055
EU="$HOME/.local/bin/ponte-tailscale"
SUDO=""; [ "$(id -u)" -ne 0 ] && sudo -n true 2>/dev/null && SUDO=sudo

instalar() {
  if ! command -v tailscale >/dev/null 2>&1; then
    # baixa para ARQUIVO e só então executa (regra da casa: nada de baixar-e-executar às cegas por pipe)
    curl -fsSL https://tailscale.com/install.sh -o /tmp/tailscale-install.sh
    $SUDO sh /tmp/tailscale-install.sh >/dev/null
  fi
  command -v ssh >/dev/null 2>&1 || { $SUDO apt-get update -qq >/dev/null; $SUDO apt-get install -y -qq openssh-client >/dev/null; }
  mkdir -p ~/.ssh "$(dirname "$EU")" ~/.claude && chmod 700 ~/.ssh
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
  cp "$0" "$EU" && chmod 755 "$EU"
  # gancho SessionStart: conecta em segundo plano a cada sessão (não atrasa o início); mescla com o settings existente
  python3 - "$EU" <<'PY'
import json, os, sys
p = os.path.expanduser("~/.claude/settings.json")
s = json.load(open(p)) if os.path.exists(p) else {}
cmd = f"nohup bash {sys.argv[1]} conectar >/tmp/ponte.log 2>&1 &"
ss = s.setdefault("hooks", {}).setdefault("SessionStart", [])
if not any(h.get("command") == cmd for g in ss for h in g.get("hooks", [])):
    ss.append({"hooks": [{"type": "command", "command": cmd}]})
json.dump(s, open(p, "w"), indent=2)
PY
  echo "ponte instalada: conecta a cada sessão (log em /tmp/ponte.log)"
}

conectar() {
  : "${TS_AUTHKEY:?defina TS_AUTHKEY (segredo OAuth tskey-client-… ou chave tag:claude-cloud) nas variáveis do ambiente}"
  command -v tailscale >/dev/null 2>&1 || instalar
  # a nuvem não tem /dev/net/tun: modo userspace + proxy SOCKS5 para ssh/http chegarem às máquinas
  if ! pgrep -x tailscaled >/dev/null 2>&1; then
    $SUDO nohup tailscaled --tun=userspace-networking --socks5-server="$SOCKS" --outbound-http-proxy-listen="$SOCKS" \
      --state=mem: >/tmp/tailscaled.log 2>&1 &
    for _ in $(seq 1 20); do tailscale status >/dev/null 2>&1 && break; [ -S /var/run/tailscale/tailscaled.sock ] && break; sleep 1; done
  fi
  # segredo OAuth: o nó é criado na hora, efêmero e com a tag (27/11/2026)
  if [[ "$TS_AUTHKEY" == tskey-client-* ]]; then
    CHAVE="${TS_AUTHKEY}?ephemeral=true&preauthorized=true"; TAGS="--advertise-tags=tag:claude-cloud"
  else
    CHAVE="$TS_AUTHKEY"; TAGS=""
  fi
  tailscale status >/dev/null 2>&1 || $SUDO tailscale up --authkey="$CHAVE" $TAGS --hostname="$NOME" --accept-dns=false
  tailscale status --peers=false 2>/dev/null | head -1
  for h in jfn-ponte jfn-agent-2 jorge; do          # VM-1, VM-2, it-campo («jorge» na rede)
    if timeout 8 tailscale ping -c 1 "$h" >/dev/null 2>&1; then echo "ok  $h"; else echo "SEM RESPOSTA  $h"; fi
  done
  echo "ponte pronta: ssh vm1 · ssh vm1 'ssh vm2-ts …' · ssh vm1 'ssh it-campo …'   (HTTP: ALL_PROXY=socks5h://$SOCKS)"
}

case "${1:-}" in
  instalar) instalar ;;
  conectar) conectar ;;
  "") instalar; [ -n "${TS_AUTHKEY:-}" ] && conectar || true ;;   # compatível com o uso antigo
  *) echo "uso: $0 [instalar|conectar]"; exit 2 ;;
esac
