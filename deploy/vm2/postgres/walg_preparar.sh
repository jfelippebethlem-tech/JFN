#!/bin/bash
# walg_preparar.sh — PREPARA o WAL-G no R2 para o PostgreSQL da VM-2, SEM ligar o arquivamento (24/11/2026).
#
#   sudo deploy/vm2/postgres/walg_preparar.sh instalar   # baixa v$VERSAO, confere o sha256 da release, instala
#   sudo deploy/vm2/postgres/walg_preparar.sh config     # /etc/wal-g/walg.yaml (postgres 600) com a chave R2 QUE JÁ
#                                                        # EXISTE no rclone.conf do dono (nenhuma chave nova)
#   sudo deploy/vm2/postgres/walg_preparar.sh provar     # objeto de prova: st put → st ls → st get (cmp) → st rm
#
# NÃO toca no postgresql.conf, não liga archive_mode (exige RESTART do PG compartilhado com o brain — a janela é do
# dono) e não roda backup-push (sem WAL arquivado o base backup não restaura sozinho: gastaria R2 à toa).
# Passo a passo completo e o que falta: deploy/vm2/postgres/backup.md §5.
# Versão: v3.0.9 (2026-08-20). A v3.0.10 saiu em 2026-11-17 — nova demais (regra: release com ≥ 2 semanas).
set -euo pipefail
VERSAO="${WALG_VERSAO:-v3.0.9}"
ART="wal-g-pg-24.04-aarch64"
CONF=/etc/wal-g/walg.yaml
PREFIXO="s3://jorgefelippe/pg-evidencias"
DONO="${SUDO_USER:-ubuntu}"
RCLONE_CONF="$(getent passwd "$DONO" | cut -d: -f6)/.config/rclone/rclone.conf"
[ "$(id -u)" -eq 0 ] || { echo "precisa de sudo"; exit 1; }
[ "$(uname -m)" = aarch64 ] || { echo "binário é aarch64; máquina é $(uname -m)"; exit 2; }

case "${1:-}" in
  instalar)
    d="$(mktemp -d)"; trap 'rm -rf "$d"' EXIT
    base="https://github.com/wal-g/wal-g/releases/download/$VERSAO"
    curl -fsSL -o "$d/$ART" "$base/$ART"
    curl -fsSL -o "$d/$ART.sha256" "$base/$ART.sha256"
    esperado="$(awk '{print $1}' "$d/$ART.sha256")"
    real="$(sha256sum "$d/$ART" | awk '{print $1}')"
    [ -n "$esperado" ] && [ "$esperado" = "$real" ] || { echo "sha256 NÃO confere ($real ≠ $esperado)"; exit 3; }
    install -o root -g root -m 755 "$d/$ART" /usr/local/bin/wal-g
    echo "instalado /usr/local/bin/wal-g ($VERSAO, sha256 $real conferido com a release)"
    /usr/local/bin/wal-g --version ;;
  config)
    [ -r "$RCLONE_CONF" ] || { echo "sem $RCLONE_CONF"; exit 4; }
    # lê a seção [r2] do rclone.conf (chave que JÁ existe) — nada é impresso
    ler() { awk -v k="$1" '/^\[/{s=($0=="[r2]")} s && $1==k {sub(/^[^=]*=[ \t]*/,""); print; exit}' "$RCLONE_CONF"; }
    ak="$(ler access_key_id)"; sk="$(ler secret_access_key)"; ep="$(ler endpoint)"
    [ -n "$ak" ] && [ -n "$sk" ] && [ -n "$ep" ] || { echo "seção [r2] incompleta no rclone.conf"; exit 4; }
    install -d -o postgres -g postgres -m 700 /etc/wal-g
    umask 077
    cat > "$CONF.novo" <<EOF
# /etc/wal-g/walg.yaml — gerado por deploy/vm2/postgres/walg_preparar.sh em $(date '+%F %T'). NÃO versionar.
# Credenciais: a chave R2 que já existia no rclone.conf (decisão delegada 24/11/2026: nenhuma chave nova).
WALG_S3_PREFIX: $PREFIXO
AWS_ENDPOINT: $ep
AWS_REGION: auto
AWS_S3_FORCE_PATH_STYLE: "true"
AWS_ACCESS_KEY_ID: $ak
AWS_SECRET_ACCESS_KEY: $sk
WALG_COMPRESSION_METHOD: zstd
WALG_DELTA_MAX_STEPS: "0"
PGHOST: /var/run/postgresql
PGUSER: postgres
PGDATABASE: jfn_evidencias
EOF
    chown postgres:postgres "$CONF.novo"; chmod 600 "$CONF.novo"; mv "$CONF.novo" "$CONF"
    echo "escrito $CONF (postgres:postgres 600; prefixo $PREFIXO; segredo não impresso)" ;;
  provar)
    W=(sudo -u postgres /usr/local/bin/wal-g --config "$CONF")
    d="$(mktemp -d)"; chown postgres:postgres "$d"; trap 'rm -rf "$d"' EXIT
    head -c 4096 /dev/urandom > "$d/prova.bin"; chown postgres:postgres "$d/prova.bin"
    nome="prova/walg-preparar-$(date +%Y%m%d%H%M%S).bin"
    "${W[@]}" st put --no-compress --no-encrypt "$d/prova.bin" "$nome"
    "${W[@]}" st ls prova/ | grep -F "$(basename "$nome")"
    "${W[@]}" st get --no-decompress --no-decrypt "$nome" "$d/volta.bin"
    cmp "$d/prova.bin" "$d/volta.bin" && echo "IDA E VOLTA OK (4096 bytes iguais)"
    "${W[@]}" st rm "$nome" && echo "objeto de prova removido (DeleteObject é grátis no R2)" ;;
  *) sed -n 2,13p "$0"; exit 2 ;;
esac
