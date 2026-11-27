#!/usr/bin/env bash
# Atualização semanal do it-campo, comandada da VM-1 (E17): o WSL (apt) como ROOT pelo lado Windows — o sudo do WSL pede
# senha e não se cria nem troca senha — e o Claude Code do WINDOWS (CLI + plugins). Windows Update e driver de GPU são
# do Windows/dono e ficam fora. Uso: tools/atualizar_itcampo.sh [--simular]
set -u
cd "$(dirname "$0")/.."
SIM="${1:-}"
saida=$(timeout 3600 ssh it-campo "wsl -d Ubuntu -u root -- env JFN_USUARIO_NO=iterj bash -s itcampo $SIM" < tools/atualizar_no.sh 2>&1)
rc=$?
echo "$saida" | grep -v "^SIMULAR" | tail -3
if [ "$SIM" = "--simular" ]; then
  echo "SIMULAR: ssh it-campo claude update; claude plugin update <cada>" >&2
  wcc="simulado"
else
  antes=$(timeout 60 ssh it-campo 'claude.cmd --version' 2>/dev/null | awk '{print $1}')
  timeout 900 ssh it-campo 'claude.cmd update' >/dev/null 2>&1 || rc=1
  for p in $(timeout 120 ssh it-campo 'claude.cmd plugin list' 2>/dev/null | grep -oE '[A-Za-z0-9._-]+@[A-Za-z0-9._-]+' | grep -v '@synced$' | sort -u); do
    timeout 300 ssh it-campo "claude.cmd plugin update $p" >/dev/null 2>&1 || rc=1
  done
  wcc="$antes→$(timeout 60 ssh it-campo 'claude.cmd --version' 2>/dev/null | awk '{print $1}')"
fi
echo "atualizar_no: {\"no\": \"itcampo-windows\", \"claude\": \"$wcc\", \"rc_wsl\": $rc}"
exit $rc
