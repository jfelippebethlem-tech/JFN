#!/bin/bash
# BACKUP OFF-BOX DIÁRIO do compliance.db pela PORTA ÚNICA de armazenamento (docs/ARMAZENAMENTO.md).
# Histórico: semanal → B2 com rclone avulso (auditoria 2026-06-18: 1,3 GB SEM backup); 24/11/2026 (decisão delegada,
# vault/refatoracao/decisoes-delegadas-infra-20261124.md): DIÁRIO, pela porta única (classe backup_db =
# insubstituível: Drive + 2ª cópia no 1º remoto grátis de `segunda_copia` que couber — o pré-voo recusa o que
# estouraria o grátis) e retenção pela porta (`armazenamento podar`).
#   quick_check → snapshot consistente A QUENTE (API de backup do SQLite em lotes, não trava escritores) +
#   quick_check do snapshot + gzip → guardar (hash conferido em cada cópia ANTES de apagar o local) → podar.
# Retenção (cabe no grátis: ~1,7 GB por cópia em 24/11): Drive guarda as 7 mais novas; cada outro remoto, as 2 mais
# novas DELE. A poda não roda se o backup de hoje não cumpriu a política (o de ontem não some por causa de hoje).
# Os 3 semanais antigos em b2:jfn-backup-jorge/compliance/ (rclone avulso) ficam como estão até a O8.2 decidir.
# VM-safe: ionice idle + nice 19. Linha "✓ off-box: …compliance-AAAAMMDD-HHMMSS.db.gz" é o que o sensor
# backup.compliance_idade_h lê (compliance_agent/fluxo/sensores.py) — não mudar o formato.
set -uo pipefail
cd /home/ubuntu/JFN || exit 1
DB=data/compliance.db
PY=.venv/bin/python
export PYTHONPATH=.
TS=$(date +%Y%m%d-%H%M%S)
ARQ="data/backups/compliance-$TS.db.gz"
PREFIXO="vm1/JFN/data/backups/compliance-"
MANTER_PRINCIPAL="${BACKUP_MANTER_PRINCIPAL:-7}"
MANTER_OUTROS="${BACKUP_MANTER_OUTROS:-2}"
mkdir -p data/backups

# 1) integridade — não faz backup de base corrompida sem avisar
INT=$($PY -c "import sqlite3;print(sqlite3.connect('$DB').execute('PRAGMA quick_check(1)').fetchone()[0])" 2>&1)
if [ "$INT" != "ok" ]; then echo "[backup] ⛔ integrity FALHOU: $INT"; exit 1; fi

# 2) snapshot a quente + quick_check do snapshot + gzip (a mesma função do `encher` da porta)
if ! ionice -c3 nice -n19 $PY -c "import sys; from pathlib import Path
from compliance_agent.armazenamento import snapshot_sqlite_gz
snapshot_sqlite_gz(Path(sys.argv[1]), Path(sys.argv[2]))" "$DB" "$ARQ"; then
  echo "[backup] ⛔ snapshot falhou"; rm -f "${ARQ%.gz}" "$ARQ"; exit 1
fi
# snapshots locais de dias que não subiram: o de hoje os substitui (cada um tem ~1,7 GB de disco)
find data/backups -maxdepth 1 -name 'compliance-*.db.gz' ! -name "$(basename "$ARQ")" -print -delete \
  | sed 's/^/[backup] snapshot local antigo removido: /'

# 3) guardar pela porta única (2 provedores, hash conferido, só então apaga o local)
OUT=$(nice -n 15 timeout 10800 $PY -m compliance_agent.armazenamento guardar "$ARQ" --classe backup_db --apagar-local)
RC=$?
echo "[backup] guardar rc=$RC $OUT"
DEST=$($PY -c "import json,sys
try:
    r = json.loads(sys.argv[1].strip().splitlines()[-1])
except (ValueError, IndexError):
    sys.exit(1)
ok = sorted(d for d, s in r['copias'].items() if s == 'ok')
print('+'.join(ok) if r.get('apagado') else '')" "$OUT")
if [ $RC -ne 0 ] || [ -z "$DEST" ]; then
  echo "[backup] ⚠️ política não cumprida (cópias acima) — snapshot local mantido em $ARQ; nada foi podado"
  exit 2
fi
echo "[backup] ✓ off-box: $DEST:$PREFIXO$TS.db.gz (porta única)"

# 4) retenção pela porta (a trava da mais nova está DENTRO do podar)
$PY -m compliance_agent.armazenamento podar --prefixo "$PREFIXO" --manter-principal "$MANTER_PRINCIPAL" \
  --manter-outros "$MANTER_OUTROS" --aplicar | sed 's/^/[backup] podar /'
