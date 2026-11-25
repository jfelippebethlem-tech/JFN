#!/bin/bash
# egress.sh — aplica/confirma/desfaz o egress dos coletores (O0.4) com AUTO-REVERSÃO.
#
#   sudo deploy/seguranca/egress.sh checar   --uid N   # só `nft -c` (não muda nada)
#   sudo deploy/seguranca/egress.sh aplicar  --uid N   # aplica + agenda reversão em 120 s
#   sudo deploy/seguranca/egress.sh confirmar          # cancela a reversão (fica valendo)
#   sudo deploy/seguranca/egress.sh desfazer           # remove a tabela inet jfn_egress
#   sudo deploy/seguranca/egress.sh verificar --uid N  # sondas como o uid do coletor
#
# A reversão é um timer do systemd (`systemd-run --on-active`), não um `sleep` desta shell: se a
# sessão SSH cair no meio, a tabela some sozinha em 120 s. Nada aqui grava em /etc/nftables.conf —
# depois de um reboot a regra NÃO volta (persistir é passo separado, com ok do dono).
# Uid 0 e uid 1001 (ubuntu: sessão do dono e PG client) são recusados de propósito.
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
MODELO="$AQUI/nftables-egress.nft"
TABELA="inet jfn_egress"
UNIDADE="jfn-egress-reverter"
PRAZO="${EGRESS_PRAZO:-120}"

uso() { sed -n '2,13p' "$0"; exit 2; }
[ "$(id -u)" -eq 0 ] || { echo "precisa de sudo"; exit 1; }
ACAO="${1:-}"; shift || true
UID_C=""
while [ $# -gt 0 ]; do
  case "$1" in --uid) UID_C="$2"; shift 2 ;; *) uso ;; esac
done

exigir_uid() {
  [[ "$UID_C" =~ ^[0-9]+$ ]] || { echo "--uid numérico obrigatório"; exit 2; }
  if [ "$UID_C" -eq 0 ] || [ "$UID_C" -eq 1001 ]; then
    echo "uid $UID_C recusado: filtrar root/ubuntu barraria a sessão do dono e o PG client"; exit 2
  fi
}

renderizar() {
  local tmp; tmp="$(mktemp /tmp/jfn-egress-XXXXXX.nft)"
  sed "s/@UID_COLETOR@/$UID_C/" "$MODELO" > "$tmp"
  echo "$tmp"
}

case "$ACAO" in
  checar)
    exigir_uid; f="$(renderizar)"; nft -c -f "$f"; rm -f "$f"; echo "OK: sintaxe aceita pelo kernel (nada aplicado)" ;;
  aplicar)
    exigir_uid; f="$(renderizar)"
    nft -c -f "$f"
    # agenda a reversão ANTES de aplicar: se o apply travar a sessão, ela já está armada
    systemctl stop "$UNIDADE.timer" 2>/dev/null || true
    systemd-run --quiet --unit "$UNIDADE" --on-active="${PRAZO}s" /usr/sbin/nft delete table $TABELA
    nft -f "$f"; rm -f "$f"
    echo "APLICADO. Reversão automática em ${PRAZO}s. Teste agora (egress.sh verificar --uid $UID_C);"
    echo "para manter: sudo $0 confirmar"
    if [ -t 0 ]; then
      if read -r -t "$PRAZO" -p "Digite CONFIRMO para manter: " resp && [ "$resp" = "CONFIRMO" ]; then
        systemctl stop "$UNIDADE.timer"; echo "CONFIRMADO — fica valendo (até reboot)."
      else
        echo; echo "sem confirmação — o timer desfaz em instantes."
      fi
    fi ;;
  confirmar)
    systemctl stop "$UNIDADE.timer" && echo "CONFIRMADO — reversão cancelada (vale até reboot)." ;;
  desfazer)
    systemctl stop "$UNIDADE.timer" 2>/dev/null || true
    if nft list table $TABELA >/dev/null 2>&1; then nft delete table $TABELA; echo "removida $TABELA"; else echo "$TABELA não existe"; fi ;;
  verificar)
    exigir_uid
    como() { setpriv --reuid="$UID_C" --regid="$UID_C" --clear-groups -- "$@"; }
    s() { if "$@" >/dev/null 2>&1; then echo "passa"; else echo "falha"; fi; }
    echo "metadata 169.254.169.254 (esperado: falha) .. $(s como curl -s -o /dev/null -m 3 http://169.254.169.254/)"
    echo "painel 127.0.0.1:8000 (esperado: falha) ..... $(s como curl -s -o /dev/null -m 3 http://127.0.0.1:8000/)"
    echo "DNS pelo stub (esperado: passa) ............ $(s como getent ahosts pncp.gov.br)"
    echo "HTTPS externo (esperado: passa) ............ $(s como curl -s -o /dev/null -m 10 https://pncp.gov.br/)"
    echo "PG VM-2 100.74.228.51:5432 (esperado: passa) $(s como timeout 3 bash -c '</dev/tcp/100.74.228.51/5432')"
    echo "SSH 10.0.0.1:22 RFC1918 (esperado: falha) .. $(s como timeout 3 bash -c '</dev/tcp/10.0.0.1/22')"
    echo "contadores:"; nft list chain $TABELA coletor | grep 'counter' || true ;;
  *) uso ;;
esac
