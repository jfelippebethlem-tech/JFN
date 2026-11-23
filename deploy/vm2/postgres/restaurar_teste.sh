#!/usr/bin/env bash
# JFN — teste de restauração do PostgreSQL de evidências, na VM-1 (docs/PLANO-PLATAFORMA-EVIDENCIAS.md, Fase 3).
#
# Restaura o ÚLTIMO backup do WAL-G (deploy/vm2/postgres/backup.md) numa instância temporária, reaplica todo o WAL
# arquivado, e confere a contagem de linhas de cada tabela contra as contagens gravadas no user-data do backup.
# Nada é anexado a log de sucesso sem conferência: qualquer divergência sai com código != 0 e grava "falhou".
#
# Uso (VM-1, como o usuário ubuntu; precisa de /usr/lib/postgresql/16/bin e /usr/local/bin/wal-g):
#     deploy/vm2/postgres/restaurar_teste.sh
#
# Idempotente: começa apagando qualquer sobra de execução anterior (instância parada, diretório removido).
# A instância temporária NUNCA arquiva WAL (archive_mode=off) — senão escreveria no mesmo prefixo da produção.
set -euo pipefail

PGBIN=/usr/lib/postgresql/16/bin
WALG=/usr/local/bin/wal-g
WALG_YAML=${WALG_YAML:-$HOME/.config/jfn/walg.yaml}      # cópia LOCAL (600) do /etc/wal-g/walg.yaml da VM-2
DIR=${JFN_RESTAURO_DIR:-/var/tmp/jfn-pg-restauro}
PORTA=55432
ESPERA_S=${JFN_RESTAURO_ESPERA_S:-1800}
RAIZ="$(cd "$(dirname "$0")/../../.." && pwd)"
SAIDA="$RAIZ/data/plataforma/restauracao_pg.json"
TABELAS=(processos arvores documentos versoes jobs)

registrar() {   # registrar <estado> <detalhe-json>
    mkdir -p "$(dirname "$SAIDA")"
    printf '{"estado": "%s", "em": "%s", "detalhe": %s}\n' "$1" "$(date '+%Y-%m-%d %H:%M:%S')" "$2" > "$SAIDA.tmp"
    mv "$SAIDA.tmp" "$SAIDA"
}
falha() {
    echo "ERRO: $*" >&2
    registrar falhou "$(printf '%s' "$*" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')"
    exit 1
}
parar() { [[ -f $DIR/postmaster.pid ]] && "$PGBIN/pg_ctl" -D "$DIR" -m immediate stop >/dev/null 2>&1 || true; }
trap parar EXIT                     # em falha o diretório FICA (restauro.log) até a próxima execução

[[ $EUID -ne 0 ]] || falha "não rode como root (o PostgreSQL recusa)"
[[ -x $PGBIN/postgres ]] || falha "faltam os binários do PostgreSQL 16 em $PGBIN (instalar só com ok do dono)"
[[ -x $WALG ]] || falha "falta $WALG"
[[ -r $WALG_YAML ]] || falha "falta $WALG_YAML"
[[ "$(stat -c %a "$WALG_YAML")" == 600 ]] || falha "$WALG_YAML precisa ser 600 (tem credencial)"
command -v python3 >/dev/null || falha "falta python3"

# 0. sobra de execução anterior (idempotência)
parar
rm -rf "$DIR"

# 1. qual é o último backup e o que ele declarou (user-data com as contagens)
LISTA=$("$WALG" --config "$WALG_YAML" backup-list --detail --json) || falha "backup-list falhou (credencial? rede?)"
read -r NOME BYTES ESPERADO < <(printf '%s' "$LISTA" | python3 -c '
import json, sys
b = json.load(sys.stdin)
if not b:
    sys.exit("nenhum backup no prefixo")
u = max(b, key=lambda x: x["start_time"])
cont = (u.get("user_data") or {}).get("contagens")
if not cont:
    sys.exit("backup sem contagens no user-data (rotina da backup.md não seguida)")
print(u["backup_name"], u.get("uncompressed_size") or 0, json.dumps(cont, separators=(",", ":")))
') || falha "não achei backup utilizável"
echo "último backup: $NOME ($BYTES bytes descomprimidos); esperado ≥ $ESPERADO"

# 2. espaço: o descomprimido + 50% de folga para o WAL reaplicado (a VM-1 já sofreu com disco cheio)
LIVRE=$(( $(df --output=avail -B1 "$(dirname "$DIR")" | tail -1) ))
(( LIVRE > BYTES * 3 / 2 )) || falha "espaço insuficiente em $(dirname "$DIR"): livre $LIVRE, preciso ~$(( BYTES * 3 / 2 ))"

# 3. restaura e prepara a recuperação até o fim do WAL arquivado
install -d -m 700 "$DIR"
nice "$WALG" --config "$WALG_YAML" backup-fetch "$DIR" "$NOME" || falha "backup-fetch falhou"
# No Debian/Ubuntu os .conf ficam em /etc e não vêm no backup: a instância temporária ganha os seus, mínimos.
cat > "$DIR/postgresql.conf" <<EOF
listen_addresses = ''
port = $PORTA
unix_socket_directories = '$DIR'
shared_buffers = 128MB
max_connections = 10
archive_mode = off
restore_command = '$WALG --config $WALG_YAML wal-fetch %f %p'
recovery_target_action = 'promote'
EOF
printf 'local all all trust\n' > "$DIR/pg_hba.conf"      # só socket dentro de um diretório 700
: > "$DIR/pg_ident.conf"
rm -f "$DIR/postgresql.auto.conf"
touch "$DIR/recovery.signal"

# 4. sobe e espera a recuperação terminar (promoção = todo WAL disponível reaplicado)
nice "$PGBIN/pg_ctl" -D "$DIR" -l "$DIR/restauro.log" -w -t 120 start >/dev/null || falha "instância temporária não subiu ($DIR/restauro.log)"
q() { "$PGBIN/psql" -h "$DIR" -p "$PORTA" -U postgres -d jfn_evidencias -v ON_ERROR_STOP=1 -qAt -c "$1"; }
for (( t = 0; t < ESPERA_S; t += 5 )); do
    [[ "$(q 'SELECT pg_is_in_recovery()' 2>/dev/null || echo t)" == f ]] && break
    sleep 5
done
[[ "$(q 'SELECT pg_is_in_recovery()')" == f ]] || falha "recuperação não terminou em ${ESPERA_S}s"

# 5. confere: cada tabela existe e tem PELO MENOS o que o backup declarou (o WAL reaplicado só acrescenta —
#    nada na plataforma apaga linha: versão antiga fica, job concluído fica)
OBTIDO="{"
for t in "${TABELAS[@]}"; do
    n=$(q "SELECT count(*) FROM $t") || falha "tabela $t ausente ou ilegível"
    OBTIDO+="\"$t\":$n,"
done
OBTIDO="${OBTIDO%,}}"
RES=$(python3 - "$ESPERADO" "$OBTIDO" <<'PY'
import json, sys
esp, obt = json.loads(sys.argv[1]), json.loads(sys.argv[2])
ruins = {t: {"esperado": esp.get(t), "obtido": obt.get(t)} for t in esp if obt.get(t, -1) < esp[t]}
if not obt.get("processos"):
    ruins["processos"] = {"esperado": "> 0", "obtido": obt.get("processos")}
print(json.dumps({"ok": not ruins, "esperado": esp, "obtido": obt, "divergencias": ruins}))
PY
)
echo "$RES"
[[ "$(printf '%s' "$RES" | python3 -c 'import json,sys;print(json.load(sys.stdin)["ok"])')" == True ]] \
    || falha "contagem divergente: $RES"
registrar ok "$(printf '%s' "$RES" | python3 -c "import json,sys;d=json.load(sys.stdin);d['backup']='$NOME';print(json.dumps(d))")"
parar; rm -rf "$DIR"
echo "restauração conferida: $NOME"
