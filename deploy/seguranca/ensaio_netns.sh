#!/bin/bash
# ensaio_netns.sh — prova o nftables-egress.nft SEM tocar no firewall da máquina (O0.4).
#
#   sudo deploy/seguranca/ensaio_netns.sh
#
# Monta dois namespaces de rede descartáveis: `coletor` (onde a regra é carregada — o nftables é
# POR namespace, a tabela do host não muda) e `mundo` (faz o papel da metadata 169.254.169.254, do
# PG da VM-2 na Tailnet, de outro nó Tailnet, de um host RFC1918 e de um HTTPS externo). Roda as
# mesmas sondas como o uid do coletor (65534 no ensaio) e como root (controle: a regra é por uid).
# Sai ≠ 0 se qualquer resultado divergir do esperado. Limpa tudo ao sair.
set -uo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "precisa de sudo"; exit 1; }
NS=jfn_o04_coletor; MU=jfn_o04_mundo; UIDC=65534
TMP="$(mktemp -d /tmp/jfn-o04-XXXXXX)"; chmod 755 "$TMP"
limpar() { ip netns pids $MU 2>/dev/null | xargs -r kill 2>/dev/null; ip netns pids $NS 2>/dev/null | xargs -r kill 2>/dev/null
           ip netns del $NS 2>/dev/null; ip netns del $MU 2>/dev/null; rm -rf "$TMP"; }
trap limpar EXIT
limpar 2>/dev/null; TMP="$(mktemp -d /tmp/jfn-o04-XXXXXX)"; chmod 755 "$TMP"

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

sed "s/@UID_COLETOR@/$UIDC/" "$AQUI/nftables-egress.nft" > "$TMP/regra.nft"
ip netns exec $NS nft -f "$TMP/regra.nft" || { echo "nft recusou a regra"; exit 1; }

tcp() { timeout 3 bash -c "</dev/tcp/$1/$2"; }
http() { curl -s -o /dev/null -m 3 "$@"; }
sonda() {  # nome  esperado_coletor  comando...
  local nome="$1" esp="$2"; shift 2
  local rc rr
  ip netns exec $NS setpriv --reuid=$UIDC --regid=$UIDC --clear-groups -- "$@" >/dev/null 2>&1 && rc=passa || rc=falha
  ip netns exec $NS "$@" >/dev/null 2>&1 && rr=passa || rr=falha
  local ok=OK; { [ "$rc" = "$esp" ] && [ "$rr" = passa ]; } || { ok=DIVERGE; FALHOU=1; }
  printf '%-44s coletor=%-6s (esperado %-6s) root=%-6s %s\n' "$nome" "$rc" "$esp" "$rr" "$ok"
}
export -f tcp http
FALHOU=0
sonda "curl metadata http://169.254.169.254/"     falha bash -c 'http http://169.254.169.254/'
sonda "HTTPS externo 93.184.216.34:443 (curl -k)"  passa bash -c 'http -k https://93.184.216.34/'
sonda "PG VM-2 Tailnet 100.74.228.51:5432"         passa bash -c 'tcp 100.74.228.51 5432'
sonda "outro nó Tailnet 100.74.228.99:5432"        falha bash -c 'tcp 100.74.228.99 5432'
sonda "RFC1918 10.0.0.1:22"                        falha bash -c 'tcp 10.0.0.1 22'
sonda "painel loopback 127.0.0.1:8000"             falha bash -c 'http http://127.0.0.1:8000/'
sonda "loopback v6 [::1]:8000"                     falha bash -c 'http "http://[::1]:8000/"'
sonda "PG local 127.0.0.1:5432"                    passa bash -c 'tcp 127.0.0.1 5432'
sonda "DNS stub 127.0.0.53:53/tcp"                 passa bash -c 'tcp 127.0.0.53 53'
echo "contadores de recusa no namespace:"
ip netns exec $NS nft list chain inet jfn_egress coletor | grep 'counter' | sed 's/^[[:space:]]*/  /'
echo "tabelas do HOST (inalteradas, sem jfn_egress):"; nft list tables | tr '\n' ' '; echo
[ $FALHOU -eq 0 ] && echo "ENSAIO OK" || echo "ENSAIO DIVERGIU"
exit $FALHOU
