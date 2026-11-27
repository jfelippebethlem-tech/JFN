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
# 25/11/2026: o .gz é cifrado com age para as chaves SSH das 3 máquinas antes de subir (tools/cifrar_backup.sh, que
# prova a volta por sha256 antes de apagar o claro): sobe compliance-AAAAMMDD-HHMMSS.db.gz.age.
# VM-safe: ionice idle + nice 19. Linha "✓ off-box: …compliance-AAAAMMDD-HHMMSS.db.gz.age" é o que o sensor
# backup.compliance_idade_h lê (compliance_agent/fluxo/sensores.py) — não mudar o formato.
set -uo pipefail
cd /home/ubuntu/JFN || exit 1
DB=data/compliance.db
PY=.venv/bin/python
export PYTHONPATH=.
TS=$(date +%Y%m%d-%H%M%S)
ARQ="$PWD/data/backups/compliance-$TS.db.gz"   # absoluto: o índice guarda o caminho como recebido (onde/obter)
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
rm -f "${ARQ%.gz}-shm" "${ARQ%.gz}-wal"    # sobras do quick_check do snapshot (o .db já virou .gz)
# snapshots locais de dias que não subiram: o de hoje os substitui (cada um tem ~1,7 GB de disco)
find "$PWD/data/backups" -maxdepth 1 -name 'compliance-*.db.gz*' ! -name "$(basename "$ARQ")" -print -delete \
  | sed 's/^/[backup] snapshot local antigo removido: /'

# 2a) a MESMA cópia consistente vira a fonte da coleta dos nós (E6/E9/E10/E11/E16 fora da VM-1): o .gz já conferido
# vai à VM-2 e ao it-campo, que conferem o md5, descompactam, quick_check e trocam atomicamente
# (compliance_agent/fluxo/fonte_coleta.py, 26/11/2026). Falha aqui NÃO derruba o backup: fica no log, e a cópia de
# cada nó vence em 48 h (o nó deixa de anunciar fonte_coleta → BLOQUEADO visível, nunca dado velho calado).
PUB=$(ionice -c3 nice -n15 timeout 7200 $PY -m compliance_agent.fluxo.fonte_coleta publicar "$ARQ" 2>&1); echo "[backup] ${PUB##*$'\n'}"

# 2b) cifra (age, 3 chaves SSH existentes) com a volta conferida; sem isso o backup não sobe (nunca em claro)
if ! CIF=$(tools/cifrar_backup.sh "$ARQ"); then
  echo "[backup] ⛔ cifragem falhou — snapshot local em claro mantido em $ARQ; nada subiu"; exit 1
fi
ARQ="$CIF"

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
echo "[backup] ✓ off-box: $DEST:$PREFIXO$TS.db.gz.age (porta única, cifrado)"

# 4) retenção pela porta (a trava da mais nova está DENTRO do podar)
$PY -m compliance_agent.armazenamento podar --prefixo "$PREFIXO" --manter-principal "$MANTER_PRINCIPAL" \
  --manter-outros "$MANTER_OUTROS" --aplicar | sed 's/^/[backup] podar /'
