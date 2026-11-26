#!/bin/bash
# egress.sh — aplica/confirma/desfaz o egress dos coletores (O0.4) com AUTO-REVERSÃO.
#
#   sudo deploy/seguranca/egress.sh checar      # só `nft -c` (não muda nada)
#   sudo deploy/seguranca/egress.sh aplicar     # aplica + agenda reversão em 120 s
#   sudo deploy/seguranca/egress.sh confirmar   # cancela a reversão (fica valendo)
#   sudo deploy/seguranca/egress.sh carregar    # aplica SEM reversão (só jfn-egress.service, depois de confirmado)
#   sudo deploy/seguranca/egress.sh desfazer    # remove a tabela inet jfn_egress
#   sudo deploy/seguranca/egress.sh estado      # a regra está carregada E aponta para o cgroup VIVO da fatia?
#   sudo deploy/seguranca/egress.sh verificar   # sondas DENTRO da fatia × FORA dela (mesmo uid)
#
# Casa por cgroup v2 (24/11: sem criar usuário): a fatia systemd de USUÁRIO jfn-coletor.slice do dono
# (uid de --dono N, padrão $SUDO_UID). O caminho tem de EXISTIR na carga (o nft o converte no ID do cgroup):
# `systemctl --user start jfn-coletor.slice` antes — aqui isso é exigido e dito, nunca contornado.
#
# A reversão é um timer do systemd (`systemd-run --on-active`), não um `sleep` desta shell: se a
# sessão SSH cair no meio, a tabela some sozinha em 120 s. Nada aqui grava em /etc — depois de um
# reboot a regra só volta pela unit de usuário jfn-egress.service (deploy/systemd), que chama `carregar`.
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
MODELO="$AQUI/nftables-egress.nft"
TABELA="inet jfn_egress"
UNIDADE="jfn-egress-reverter"
PRAZO="${EGRESS_PRAZO:-120}"
FATIA="jfn-coletor.slice"

uso() { sed -n '2,10p' "$0"; exit 2; }
[ "$(id -u)" -eq 0 ] || { echo "precisa de sudo"; exit 1; }
ACAO="${1:-}"; shift || true
DONO="${SUDO_UID:-}"
while [ $# -gt 0 ]; do
  case "$1" in --dono) DONO="$2"; shift 2 ;; *) uso ;; esac
done
[[ "$DONO" =~ ^[0-9]+$ ]] && [ "$DONO" -ne 0 ] || { echo "--dono <uid> numérico (≠ 0) obrigatório fora do sudo"; exit 2; }
NOME_DONO="$(getent passwd "$DONO" | cut -d: -f1)"
[ -n "$NOME_DONO" ] || { echo "uid $DONO sem usuário"; exit 2; }
CGROUP="user.slice/user-$DONO.slice/user@$DONO.service/jfn.slice/$FATIA"
NIVEL="$(awk -F/ '{print NF}' <<< "$CGROUP")"
DIR="/sys/fs/cgroup/$CGROUP"

exigir_fatia() {
  [ -d "$DIR" ] || { echo "cgroup $DIR não existe: rode 'systemctl --user start $FATIA' como uid $DONO antes"; exit 3; }
}

renderizar() {
  local tmp; tmp="$(mktemp /tmp/jfn-egress-XXXXXX.nft)"
  sed -e "s|@CGROUP@|$CGROUP|" -e "s|@NIVEL@|$NIVEL|" "$MODELO" > "$tmp"
  echo "$tmp"
}

carregar() {
  exigir_fatia; local f; f="$(renderizar)"
  nft -c -f "$f"; nft -f "$f"; rm -f "$f"
}

# como o dono, num escopo transitório DENTRO da fatia (é assim que o supervisor lança os jobs)
na_fatia() {
  runuser -u "$NOME_DONO" -- env XDG_RUNTIME_DIR="/run/user/$DONO" \
    systemd-run --user --scope --quiet --slice="$FATIA" -- "$@"
}
fora() { runuser -u "$NOME_DONO" -- "$@"; }

case "$ACAO" in
  checar)
    exigir_fatia; f="$(renderizar)"; nft -c -f "$f"; rm -f "$f"
    echo "OK: sintaxe aceita pelo kernel, cgroup $CGROUP (nível $NIVEL) existe — nada aplicado" ;;
  aplicar)
    exigir_fatia; f="$(renderizar)"
    nft -c -f "$f"
    # agenda a reversão ANTES de aplicar: se o apply travar a sessão, ela já está armada
    systemctl stop "$UNIDADE.timer" 2>/dev/null || true
    systemd-run --quiet --unit "$UNIDADE" --on-active="${PRAZO}s" /usr/sbin/nft delete table $TABELA
    nft -f "$f"; rm -f "$f"
    echo "APLICADO (fatia $CGROUP). Reversão automática em ${PRAZO}s. Teste agora (egress.sh verificar);"
    echo "para manter: sudo $0 confirmar"
    if [ -t 0 ]; then
      if read -r -t "$PRAZO" -p "Digite CONFIRMO para manter: " resp && [ "$resp" = "CONFIRMO" ]; then
        systemctl stop "$UNIDADE.timer"; echo "CONFIRMADO — fica valendo (até reboot)."
      else
        echo; echo "sem confirmação — o timer desfaz em instantes."
      fi
    fi ;;
  confirmar)
    systemctl stop "$UNIDADE.timer" && echo "CONFIRMADO — reversão cancelada (vale até reboot; no boot: jfn-egress.service)." ;;
  carregar)
    carregar && echo "carregada $TABELA para $CGROUP (sem reversão)" ;;
  desfazer)
    systemctl stop "$UNIDADE.timer" 2>/dev/null || true
    if nft list table $TABELA >/dev/null 2>&1; then nft delete table $TABELA; echo "removida $TABELA"; else echo "$TABELA não existe"; fi ;;
  estado)
    # O nft lista o caminho a partir do ID guardado: ID que ainda é o da fatia viva → mostra o caminho; fatia
    # religada (ID velho) → sai o NÚMERO (medido: `socket cgroupv2 level 5 3510244`). Sem regra ou com ID velho =
    # falha ABERTA: sai ≠ 0. A listagem vai para variável: `nft … | grep -q` com pipefail dá SIGPIPE e falso "órfã".
    regra="$(nft list chain $TABELA saida 2>/dev/null)" || { echo "SEM REGRA ($TABELA ausente)"; exit 4; }
    if grep -qF "\"$CGROUP\"" <<< "$regra"; then
      echo "OK: regra carregada e casando o cgroup vivo $CGROUP (inode $(stat -c %i "$DIR"))"
    else
      echo "REGRA ÓRFÃ: aponta para um cgroup que não é mais o da fatia — rode 'egress.sh carregar'"
      grep cgroupv2 <<< "$regra"; exit 5
    fi ;;
  verificar)
    exigir_fatia
    s() { if "$@" >/dev/null 2>&1; then echo "passa"; else echo "falha"; fi; }
    linha() {  # rótulo  esperado_na_fatia  comando...
      local r="$1" e="$2"; shift 2
      printf '%-38s fatia=%-5s (esperado %-5s) fora=%-5s\n' "$r" "$(s na_fatia "$@")" "$e" "$(s fora "$@")"
    }
    linha "metadata 169.254.169.254"     falha curl -s -o /dev/null -m 3 http://169.254.169.254/
    linha "painel 127.0.0.1:8000"         passa timeout 3 bash -c '</dev/tcp/127.0.0.1/8000'
    linha "DNS pelo stub"                 passa getent ahosts www.google.com
    linha "HTTPS externo www.google.com"   passa curl -s -o /dev/null -m 10 https://www.google.com/
    linha "PG VM-2 100.74.228.51:5432"    passa timeout 3 bash -c '</dev/tcp/100.74.228.51/5432'
    linha "brain VM-2 100.74.228.51:8443" passa timeout 3 bash -c '</dev/tcp/100.74.228.51/8443'
    linha "Yoda/VNC 127.0.0.1:6080"       falha timeout 3 bash -c '</dev/tcp/127.0.0.1/6080'
    linha "SSH 10.0.0.1:22 RFC1918"       falha timeout 3 bash -c '</dev/tcp/10.0.0.1/22'
    echo "contadores:"; nft list chain $TABELA coletor | grep 'counter' || true ;;
  *) uso ;;
esac
