#!/usr/bin/env bash
# Nó-PONTE na VM-1 (dono, 27/11/2026: «criar outro nó com tag seria melhor? assim não precisa apagar a outra»).
# Um SEGUNDO tailscaled, em modo usuário e com estado próprio, chamado `jfn-ponte`, com tag:jfn e Tailscale SSH: é a
# única porta das sessões do claude.ai/code na nuvem (tag:claude-cloud → tag:jfn). O nó original da VM-1 (jfn-core:
# identidade, Funnel do painel, acesso do dono) NÃO muda. Desligar a ponte: systemctl --user stop jfn-ponte.
# Uso (uma vez): TS_AUTHKEY_PONTE=<chave com tag:jfn, NÃO efêmera> tools/nuvem/no_ponte_vm1.sh instalar
#        depois:  tools/nuvem/no_ponte_vm1.sh estado
set -euo pipefail
D="$HOME/.local/share/tailscale-ponte"; SOCK="$D/tailscaled.sock"; NOME=jfn-ponte
ts(){ tailscale --socket="$SOCK" "$@"; }
case "${1:-estado}" in
  instalar)
    : "${TS_AUTHKEY_PONTE:?defina TS_AUTHKEY_PONTE (chave com tag:jfn; não efêmera; pode ser de uso único)}"
    mkdir -p "$D" ~/.config/systemd/user
    cat > ~/.config/systemd/user/jfn-ponte.service <<EOF
[Unit]
Description=Nó-ponte Tailscale (jfn-ponte, tag:jfn) — entrada das sessões do claude.ai/code na nuvem
After=network-online.target

[Service]
ExecStart=/usr/sbin/tailscaled --tun=userspace-networking --statedir=$D --socket=$SOCK --port=41642
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now jfn-ponte.service
    for _ in $(seq 1 20); do [ -S "$SOCK" ] && break; sleep 1; done
    ts up --authkey="$TS_AUTHKEY_PONTE" --hostname="$NOME" --ssh --advertise-tags=tag:jfn --accept-dns=false
    ts status --peers=false | head -2 ;;
  estado)
    systemctl --user is-active jfn-ponte.service 2>/dev/null || true
    [ -S "$SOCK" ] && ts status --peers=false 2>/dev/null | head -2 || echo "ponte não instalada" ;;
  parar)
    systemctl --user disable --now jfn-ponte.service ;;
  *) echo "uso: $0 instalar|estado|parar"; exit 2 ;;
esac
