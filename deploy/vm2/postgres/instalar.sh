#!/usr/bin/env bash
# JFN — instala o PostgreSQL 16 da plataforma de evidências na VM-2 (docs/PLANO-PLATAFORMA-EVIDENCIAS.md, Fase 3).
#
# Uso (na VM-2, como root, a partir do repositório):
#     sudo deploy/vm2/postgres/instalar.sh
#     sudo JFN_PG_SEM_BACKUP=1 deploy/vm2/postgres/instalar.sh   # só se o WAL-G ainda não estiver configurado:
#                                                                # sobe com archive_mode=off e AVISA (ver backup.md)
#
# Idempotente: rodar de novo não troca a senha, não duplica linhas do pg_hba e só reinicia o serviço se a
# configuração mudou. Falha alto (set -e) em qualquer passo.
#
# Credencial: a senha do papel jfn_evidencias é gerada aqui UMA vez e gravada só em
# ~ubuntu/.config/jfn/evidencias.env (600) como JFN_EVIDENCIAS_DSN — nunca em git nem em log. Acrescentar ao
# ~/CREDENCIAIS.md (regra do dono, 21/11) à mão.
set -euo pipefail

PGV=16
BANCO=jfn_evidencias
PAPEL=jfn_evidencias
IP_TAILSCALE=100.74.228.51          # VM-2 na Tailnet
REDE_TAILNET=100.64.0.0/10          # faixa CGNAT do Tailscale
AQUI="$(cd "$(dirname "$0")" && pwd)"
CONF_DIR=/etc/postgresql/$PGV/main
DONO_ENV=ubuntu
ARQ_ENV=/home/$DONO_ENV/.config/jfn/evidencias.env
WALG_YAML=/etc/wal-g/walg.yaml

falha() { echo "ERRO: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || falha "rode como root (sudo)"
[[ "$(hostname)" != "jfn-core" ]] || falha "isto é a VM-1 (jfn-core): o banco canônico mora na VM-2"
ip -4 addr show | grep -q "inet $IP_TAILSCALE/" || falha "IP $IP_TAILSCALE não está nesta máquina (é a VM-2? o tailscale está de pé?)"

# 1. pacotes (o Ubuntu 24.04 já traz o PostgreSQL 16 no repositório oficial)
if ! dpkg -s "postgresql-$PGV" >/dev/null 2>&1; then
    apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q "postgresql-$PGV"
fi
[[ -d $CONF_DIR ]] || falha "$CONF_DIR não existe após a instalação"

# 2. bind no IP da Tailnet mesmo se o tailscale0 subir depois do PostgreSQL no boot
echo "net.ipv4.ip_nonlocal_bind = 1" > /etc/sysctl.d/90-jfn-postgres.conf
sysctl -q -p /etc/sysctl.d/90-jfn-postgres.conf

# 3. configuração (conf.d) — compara antes de copiar para saber se precisa reiniciar
mudou=0
mkdir -p "$CONF_DIR/conf.d"
if ! cmp -s "$AQUI/postgresql.conf.d/jfn.conf" "$CONF_DIR/conf.d/jfn.conf"; then
    install -o postgres -g postgres -m 644 "$AQUI/postgresql.conf.d/jfn.conf" "$CONF_DIR/conf.d/jfn.conf"
    mudou=1
fi
# Sem WAL-G configurado o archive_command falharia e o pg_wal cresceria até encher o disco (que é justamente o
# recurso escasso da VM-2). Ou há walg.yaml, ou o dono pediu explicitamente para subir sem backup.
SEM_BACKUP="$CONF_DIR/conf.d/zz-jfn-sem-backup.conf"
if [[ -r $WALG_YAML && -x /usr/local/bin/wal-g ]]; then
    [[ -e $SEM_BACKUP ]] && { rm -f "$SEM_BACKUP"; mudou=1; }
elif [[ "${JFN_PG_SEM_BACKUP:-0}" == "1" ]]; then
    if [[ ! -e $SEM_BACKUP ]]; then
        printf "# TEMPORÁRIO: instalar.sh rodou sem WAL-G. Apagar ao configurar o backup (backup.md) e reiniciar.\narchive_mode = off\n" > "$SEM_BACKUP"
        chown postgres:postgres "$SEM_BACKUP"
        mudou=1
    fi
    echo "AVISO: PostgreSQL SEM arquivamento de WAL (sem backup contínuo). Configure o WAL-G (backup.md) e rode de novo." >&2
else
    falha "falta $WALG_YAML ou /usr/local/bin/wal-g — configure o WAL-G (backup.md) ou rode com JFN_PG_SEM_BACKUP=1"
fi

# 4. pg_hba: bloco gerenciado entre marcadores (substituído inteiro a cada execução, nunca duplicado).
#    Só o papel da plataforma, só o banco dele, só loopback e Tailnet, só scram.
HBA="$CONF_DIR/pg_hba.conf"
BLOCO=$(cat <<EOF
# >>> JFN evidências (deploy/vm2/postgres/instalar.sh) — não editar dentro do bloco
host    $BANCO    $PAPEL    127.0.0.1/32       scram-sha-256
host    $BANCO    $PAPEL    $REDE_TAILNET      scram-sha-256
# <<< JFN evidências
EOF
)
novo=$(awk '/^# >>> JFN evidências/{pula=1} !pula{print} /^# <<< JFN evidências/{pula=0}' "$HBA")
novo="$novo"$'\n'"$BLOCO"
if [[ "$novo" != "$(cat "$HBA")" ]]; then
    cp -a "$HBA" "$HBA.antes-jfn.$(date +%Y%m%d%H%M%S)"
    printf '%s\n' "$novo" > "$HBA"
    chown postgres:postgres "$HBA"; chmod 640 "$HBA"
    mudou=1
fi

# 5. aplica (restart: listen_addresses, shared_buffers e archive_mode exigem reinício, reload não basta)
systemctl enable -q "postgresql@$PGV-main"
if [[ $mudou -eq 1 ]] || ! systemctl is-active -q "postgresql@$PGV-main"; then
    systemctl restart "postgresql@$PGV-main"
fi
for _ in $(seq 30); do pg_isready -q -h 127.0.0.1 -p 5432 && break; sleep 1; done
pg_isready -q -h 127.0.0.1 -p 5432 || falha "PostgreSQL não respondeu em 127.0.0.1:5432 (journalctl -u postgresql@$PGV-main)"

# 6. papel e banco (a senha só é criada se o papel ainda não existe)
psql_su() { sudo -u postgres psql -v ON_ERROR_STOP=1 -qAt "$@"; }
if [[ -z "$(psql_su -c "SELECT 1 FROM pg_roles WHERE rolname='$PAPEL'")" ]]; then
    [[ -e $ARQ_ENV ]] && falha "$ARQ_ENV existe mas o papel não: conferir à mão antes de gerar senha nova"
    SENHA=$(openssl rand -hex 24)                 # hex: sem caractere que precise de escape no DSN
    psql_su -c "CREATE ROLE $PAPEL LOGIN PASSWORD '$SENHA'" >/dev/null
    install -d -o "$DONO_ENV" -g "$DONO_ENV" -m 700 "$(dirname "$ARQ_ENV")"
    umask 077
    printf 'JFN_EVIDENCIAS_DSN=postgresql://%s:%s@127.0.0.1:5432/%s\n' "$PAPEL" "$SENHA" "$BANCO" > "$ARQ_ENV"
    chown "$DONO_ENV:$DONO_ENV" "$ARQ_ENV"; chmod 600 "$ARQ_ENV"
    unset SENHA
    echo "papel $PAPEL criado; DSN em $ARQ_ENV (acrescentar ao ~/CREDENCIAIS.md)"
fi
if [[ -z "$(psql_su -c "SELECT 1 FROM pg_database WHERE datname='$BANCO'")" ]]; then
    psql_su -c "CREATE DATABASE $BANCO OWNER $PAPEL ENCODING 'UTF8' TEMPLATE template0" >/dev/null
fi
psql_su -d "$BANCO" -c "REVOKE ALL ON DATABASE $BANCO FROM PUBLIC; REVOKE CREATE ON SCHEMA public FROM PUBLIC" >/dev/null

# 7. conferência final: o que está valendo de fato (não o que o arquivo diz)
echo "--- valendo:"
psql_su -c "SELECT name || ' = ' || setting FROM pg_settings WHERE name IN
  ('listen_addresses','shared_buffers','effective_cache_size','work_mem','maintenance_work_mem',
   'max_connections','wal_level','archive_mode','archive_command') ORDER BY name"
ss -ltnH '( sport = :5432 )' | awk '{print "escutando " $4}'
echo "ok"
