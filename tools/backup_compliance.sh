#!/bin/bash
# BACKUP OFF-BOX da compliance.db (auditoria 2026-06-18: 1,3GB SEM backup = perda total se
# a VM cair ou o WAL corromper). integrity_check -> snapshot consistente A QUENTE (não bloqueia
# os sweeps) -> gzip -> B2 (upload egress-zero) -> rotação (mantém os 3 mais novos).
# VM-safe: ionice idle + nice 19 (cede aos sweeps na VM de 2 vCPU).
set -uo pipefail
cd /home/ubuntu/JFN || exit 1
DB=data/compliance.db
PY=.venv/bin/python
RC=$(command -v rclone || echo "$HOME/.local/bin/rclone")
DEST="b2:jfn-backup-jorge/compliance"
TS=$(date +%Y%m%d-%H%M%S)
SNAP="/tmp/compliance-$TS.db"

# 1) integridade — não faz backup de base corrompida sem avisar
INT=$($PY -c "import sqlite3;print(sqlite3.connect('$DB').execute('PRAGMA quick_check(1)').fetchone()[0])" 2>&1)
if [ "$INT" != "ok" ]; then echo "[backup] ⛔ integrity FALHOU: $INT"; exit 1; fi

# 2) snapshot a quente (hot backup; copia páginas em lotes com micro-pausa = não trava escritores)
ionice -c3 nice -n19 $PY - "$DB" "$SNAP" <<'PYBK'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(src); b = sqlite3.connect(dst)
with b: s.backup(b, pages=2000, sleep=0.05)
b.close(); s.close()
PYBK
[ -f "$SNAP" ] || { echo "[backup] ⛔ snapshot não criado"; exit 1; }
gzip -1 "$SNAP"

# 3) upload B2 + rotação (mantém 3 mais novos)
if $RC copy "$SNAP.gz" "$DEST/" 2>/dev/null; then
  $RC lsf "$DEST/" 2>/dev/null | sort | head -n -3 | while read -r old; do $RC deletefile "$DEST/$old" 2>/dev/null; done
  echo "[backup] ✓ off-box: $DEST/$(basename "$SNAP").gz (rotação: 3 mais novos)"
else
  echo "[backup] ⚠️ upload B2 falhou — snapshot local em $SNAP.gz"
  exit 2
fi
rm -f "$SNAP.gz"
