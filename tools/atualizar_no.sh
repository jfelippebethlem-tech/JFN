#!/usr/bin/env bash
# Atualização SEMANAL de um nó (E17 manter; dono 27/11/2026: «uma vez por semana isso acontecesse sem eu precisar pedir»).
# Roda NO nó. Uso: tools/atualizar_no.sh <vm1|vm2|itcampo> [--simular]
#   1. apt: update + upgrade (não interativo, mantém config local); limpeza do que sobrou
#   2. Claude Code (CLI) e plugins do usuário
#   3. reinício SÓ se o kernel pedir (/var/run/reboot-required) e o nó não for o it-campo (lá o kernel é do Windows):
#      agendado para +2 min, DEPOIS de registrar o resultado — o motor devolve os jobs (parada não gasta tentativa) e
#      os serviços sobem sozinhos (systemd); a saúde do nó é conferida pelos sensores do E18 na volta.
# Não mexe: dependências Python dos venvs (só pelo lock com hashes, revisado), driver de GPU e Windows (do dono).
# Saída: uma linha `atualizar_no: {json}` (o efeito da rotina confere essa linha).
set -u
NO="${1:?nó: vm1|vm2|itcampo}"; MODO="${2:-}"
SIM=0; [ "$MODO" = "--simular" ] && SIM=1
export DEBIAN_FRONTEND=noninteractive
if [ "$(id -u)" = "0" ]; then SU=""; else SU="sudo -n"; fi
USUARIO="${JFN_USUARIO_NO:-$(logname 2>/dev/null || echo "${SUDO_USER:-$USER}")}"
como_usuario(){ if [ "$(id -u)" = "0" ] && [ -n "$USUARIO" ] && [ "$USUARIO" != "root" ]; then su - "$USUARIO" -c "$*"; else bash -lc "$*"; fi; }
rodar(){ if [ $SIM = 1 ]; then echo "SIMULAR: $*" >&2; else eval "$@"; fi; }
ini=$(date +%s); erros=()

# 1) sistema
$SU apt-get update -qq >/dev/null 2>&1 || erros+=("apt update")
pend=$(apt list --upgradable 2>/dev/null | grep -vc "^Listing")
if [ "$pend" -gt 0 ]; then
  rodar "$SU apt-get -y -qq -o Dpkg::Options::=--force-confold -o Dpkg::Options::=--force-confdef upgrade >/dev/null 2>&1" \
    || erros+=("apt upgrade")
  rodar "$SU apt-get -y -qq autoremove >/dev/null 2>&1" || true
fi
restam=$(apt list --upgradable 2>/dev/null | grep -vc "^Listing")

# 2) Claude Code e plugins (do usuário do nó). No it-campo o Claude Code é a instalação do WINDOWS (o `claude` do WSL é
#    o atalho do npm do Windows): quem atualiza é tools/atualizar_itcampo.sh, do lado Windows.
if [ "$NO" = "itcampo" ]; then cc_antes="windows"; cc_depois="windows"; else
cc_antes=$(como_usuario "claude --version 2>/dev/null" | awk '{print $1}')
rodar "como_usuario 'claude update >/dev/null 2>&1'" || erros+=("claude update")
rodar "como_usuario 'claude plugin marketplace update >/dev/null 2>&1'" || true
for p in $(como_usuario "claude plugin list 2>/dev/null" | grep -oE '[A-Za-z0-9._-]+@[A-Za-z0-9._-]+' | grep -v '@synced$' | sort -u); do
  rodar "como_usuario 'claude plugin update $p >/dev/null 2>&1'" || erros+=("plugin $p")
done
cc_depois=$(como_usuario "claude --version 2>/dev/null" | awk '{print $1}')
fi

# 3) reinício só quando o kernel pede (nunca no it-campo: o kernel do WSL é do Windows)
reinicio="nao_precisa"
if [ -f /var/run/reboot-required ]; then
  if [ "$NO" = "itcampo" ]; then reinicio="pendente_windows"
  else reinicio="agendado_+2min"; fi
fi

erros_json=$(printf '%s\n' "${erros[@]:-}" | python3 -c 'import json,sys; print(json.dumps([l.strip() for l in sys.stdin if l.strip()], ensure_ascii=False))')
echo "atualizar_no: {\"no\": \"$NO\", \"simular\": $SIM, \"apt_pendentes\": $pend, \"apt_restam\": $restam, \"claude\": \"$cc_antes→$cc_depois\", \"reinicio\": \"$reinicio\", \"erros\": $erros_json, \"s\": $(( $(date +%s) - ini ))}"
if [ "$reinicio" = "agendado_+2min" ] && [ $SIM = 0 ]; then $SU shutdown -r +2 "atualização semanal do JFN (E17)" >/dev/null 2>&1; fi
[ ${#erros[@]} -eq 0 ]
