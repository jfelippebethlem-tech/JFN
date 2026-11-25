#!/bin/bash
# ensaio_netns.sh — prova o nftables-egress.nft SEM tocar no firewall da máquina (O0.4).
#
#   sudo deploy/seguranca/ensaio_netns.sh [--religar]
#
# Monta dois namespaces de rede descartáveis: `coletor` (onde a regra é carregada — o nftables é
# POR namespace, a tabela do host não muda) e `mundo` (faz o papel da metadata 169.254.169.254, do
# PG da VM-2 na Tailnet, de outro nó Tailnet, de um host RFC1918 e de um HTTPS externo).
# Casa por cgroup v2 (24/11): a regra é renderizada com o caminho REAL da fatia de usuário
# jfn-coletor.slice do dono ($SUDO_UID) — a fatia tem de estar de pé (`systemctl --user start
# jfn-coletor.slice`). Cada sonda roda três vezes: (1) num escopo DENTRO da fatia, como o supervisor
# lança os jobs (systemd-run --user --scope --slice=…; o `sudo ip netns exec` não muda o cgroup);
# (2) controle: root fora da fatia; (3) controle: o MESMO uid do dono fora da fatia — prova que o
# filtro é pelo cgroup, não pelo usuário.
# --religar: depois das sondas, para e sobe a fatia (só se estiver VAZIA) e mede a ARMADILHA 2: com
# o ID velho a regra deixa de casar (metadata passa = falha aberta); recarregada, volta a recusar.
# Sai ≠ 0 se qualquer resultado divergir do esperado. Limpa tudo ao sair.
set -uo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "precisa de sudo"; exit 1; }
RELIGAR=0; [ "${1:-}" = "--religar" ] && RELIGAR=1
DONO="${SUDO_UID:?rode com sudo a partir do usuário dono da fatia}"
NOME_DONO="$(getent passwd "$DONO" | cut -d: -f1)"
FATIA=jfn-coletor.slice
CGROUP="user.slice/user-$DONO.slice/user@$DONO.service/jfn.slice/$FATIA"
NIVEL="$(awk -F/ '{print NF}' <<< "$CGROUP")"
[ -d "/sys/fs/cgroup/$CGROUP" ] || { echo "fatia ausente: systemctl --user start $FATIA (como $NOME_DONO)"; exit 3; }
NS=jfn_o04_coletor; MU=jfn_o04_mundo
TMP="$(mktemp -d /tmp/jfn-o04-XXXXXX)"; chmod 755 "$TMP"
limpar() { ip netns pids $MU 2>/dev/null | xargs -r kill 2>/dev/null; ip netns pids $NS 2>/dev/null | xargs -r kill 2>/dev/null
           ip netns del $NS 2>/dev/null; ip netns del $MU 2>/dev/null; rm -rf "$TMP"; }
trap limpar EXIT
limpar 2>/dev/null; TMP="$(mktemp -d /tmp/jfn-o04-XXXXXX)"; chmod 755 "$TMP"
como_dono() { runuser -u "$NOME_DONO" -- env XDG_RUNTIME_DIR="/run/user/$DONO" "$@"; }

ip netns add $NS; ip netns add $MU
ip link add o04c netns $NS type veth peer name o04m netns $MU
ip -n $NS link set lo up; ip -n $NS link set o04c up
ip -n $NS addr add 203.0.113.2/24 dev o04c; ip -n $NS route add default dev o04c
ip -n $MU link set lo up; ip -n $MU link set o04m up; ip -n $MU addr add 203.0.113.1/24 dev o04m
for a in 169.254.169.254 100.74.228.51 100.74.228.99 10.0.0.1 93.184.216.34; do ip -n $MU addr add $a/32 dev o04m; done
ip -n $MU route add 203.0.113.0/24 dev o04m 2>/dev/null

openssl req -x509 -newkey rsa:2048 -nodes -keyout "$TMP/k.pem" -out "$TMP/c.pem" -days 1 -subj "/CN=ensaio" 2>/dev/null
cat > "$TMP/srv.py" <<'EOF'
import socket, ssl, sys, threading
def servir(host, porta, tls=None):
    fam = socket.AF_INET6 if ":" in host else socket.AF_INET
    s = socket.socket(fam); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind((host, porta)); s.listen(16)
    while True:
        c, _ = s.accept()
        try:
            if tls: c = tls.wrap_socket(c, server_side=True)
            c.recv(4096); c.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok")
        except (OSError, ssl.SSLError):
            pass
        finally:
            c.close()
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(sys.argv[1], sys.argv[2])
alvos = [a.split("/") for a in sys.argv[3:]]
for host, porta, tls in alvos:
    threading.Thread(target=servir, args=(host, int(porta), ctx if tls == "tls" else None), daemon=True).start()
threading.Event().wait()
EOF
ip netns exec $MU python3 "$TMP/srv.py" "$TMP/c.pem" "$TMP/k.pem" 169.254.169.254/80/- 100.74.228.51/5432/- \
   100.74.228.99/5432/- 10.0.0.1/22/- 93.184.216.34/443/tls >/dev/null 2>&1 &
ip netns exec $NS python3 "$TMP/srv.py" "$TMP/c.pem" "$TMP/k.pem" 127.0.0.1/8000/- 127.0.0.1/5432/- \
   127.0.0.53/53/- ::1/8000/- >/dev/null 2>&1 &
sleep 1.5

# nsenter (não `ip netns exec`): o `ip netns exec` remonta /sys para o namespace e some /sys/fs/cgroup — o nft
# resolve o caminho da fatia por ali (medido: "cgroupv2 path fails: No such file or directory")
sed -e "s|@CGROUP@|$CGROUP|" -e "s|@NIVEL@|$NIVEL|" "$AQUI/nftables-egress.nft" > "$TMP/regra.nft"
nsenter --net=/run/netns/$NS nft -f "$TMP/regra.nft" || { echo "nft recusou a regra"; exit 1; }
echo "regra: socket cgroupv2 level $NIVEL \"$CGROUP\" (inode $(stat -c %i "/sys/fs/cgroup/$CGROUP"))"

na_fatia() { como_dono systemd-run --user --scope --quiet --slice=$FATIA -- sudo -n ip netns exec $NS "$@"; }
sonda() {  # nome  esperado_na_fatia  comando...
  local nome="$1" esp="$2"; shift 2
  local rc rr ru
  na_fatia "$@" >/dev/null 2>&1 && rc=passa || rc=falha
  ip netns exec $NS "$@" >/dev/null 2>&1 && rr=passa || rr=falha
  ip netns exec $NS setpriv --reuid="$DONO" --regid="$DONO" --clear-groups -- "$@" >/dev/null 2>&1 && ru=passa || ru=falha
  local ok=OK; { [ "$rc" = "$esp" ] && [ "$rr" = passa ] && [ "$ru" = passa ]; } || { ok=DIVERGE; FALHOU=1; }
  printf '%-42s fatia=%-5s (esp. %-5s) root=%-5s uid%s-fora=%-5s %s\n' "$nome" "$rc" "$esp" "$rr" "$DONO" "$ru" "$ok"
}
FALHOU=0
sonda "curl metadata http://169.254.169.254/"     falha curl -s -o /dev/null -m 3 http://169.254.169.254/
sonda "HTTPS externo 93.184.216.34:443 (curl -k)"  passa curl -s -o /dev/null -m 3 -k https://93.184.216.34/
sonda "PG VM-2 Tailnet 100.74.228.51:5432"         passa timeout 3 bash -c '</dev/tcp/100.74.228.51/5432'
sonda "outro nó Tailnet 100.74.228.99:5432"        falha timeout 3 bash -c '</dev/tcp/100.74.228.99/5432'
sonda "RFC1918 10.0.0.1:22"                        falha timeout 3 bash -c '</dev/tcp/10.0.0.1/22'
sonda "painel loopback 127.0.0.1:8000"             falha curl -s -o /dev/null -m 3 http://127.0.0.1:8000/
sonda "loopback v6 [::1]:8000"                     falha curl -s -o /dev/null -m 3 "http://[::1]:8000/"
sonda "PG local 127.0.0.1:5432"                    passa timeout 3 bash -c '</dev/tcp/127.0.0.1/5432'
sonda "DNS stub 127.0.0.53:53/tcp"                 passa timeout 3 bash -c '</dev/tcp/127.0.0.53/53'
echo "contadores de recusa no namespace:"
ip netns exec $NS nft list chain inet jfn_egress coletor | grep 'counter' | sed 's/^[[:space:]]*/  /'
if [ $RELIGAR -eq 1 ]; then
  if [ "$(como_dono systemctl --user show -p TasksCurrent --value $FATIA)" != "0" ]; then
    echo "--religar recusado: a fatia tem processos (não paro job vivo)"; FALHOU=1
  else
    como_dono systemctl --user stop $FATIA; como_dono systemctl --user start $FATIA
    echo "fatia religada: inode novo $(stat -c %i "/sys/fs/cgroup/$CGROUP")"
    sonda "ARMADILHA 2: ID velho, metadata"             passa curl -s -o /dev/null -m 3 http://169.254.169.254/
    nsenter --net=/run/netns/$NS nft -f "$TMP/regra.nft" || { echo "recarga recusada"; FALHOU=1; }
    sonda "recarregada: metadata"                       falha curl -s -o /dev/null -m 3 http://169.254.169.254/
  fi
fi
echo "tabelas do HOST (inalteradas, sem jfn_egress):"; nft list tables | tr '\n' ' '; echo
[ $FALHOU -eq 0 ] && echo "ENSAIO OK" || echo "ENSAIO DIVERGIU"
exit $FALHOU
