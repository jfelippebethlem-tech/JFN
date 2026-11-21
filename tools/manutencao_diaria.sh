#!/bin/bash
# Guard de OOM: este sweep morre ANTES da sessão do dono (ver tools/lib/oom_guard.sh).
source "$(dirname "$0")/lib/oom_guard.sh" 2>/dev/null || true
# Manutenção DIÁRIA leve da compliance.db (auditoria 2026-06-18): ANALYZE (planner escolhe os
# índices certos após ingestões diárias de centenas de milhares de linhas — OB/folha/doações) +
# wal_checkpoint(TRUNCATE) para o WAL não crescer entre os VACUUMs semanais. NÃO faz VACUUM (caro;
# segue no semanal). VM-safe: ionice idle + nice 19; barato (segundos). Adia se a base estiver em uso pesado.
cd /home/ubuntu/JFN || exit 1
DB=data/compliance.db
# load-guard só para o ANALYZE (caro). O CHECKPOINT roda SEMPRE: 20/11/2026 o WAL chegou a 5,96 GB (= o banco)
# porque a VM vive com load ≥ 3 e esta rodada era pulada inteira dia após dia — o disco foi a 95%.
L=$(awk '{print int($1)}' /proc/loadavg)
ANALISAR=1; [ "${L:-0}" -ge 3 ] && { ANALISAR=0; echo "[manut-diaria] load=$L alto — só checkpoint, sem ANALYZE"; }
ionice -c3 nice -n19 .venv/bin/python - "$DB" "$ANALISAR" <<'PY'
import sqlite3, sys
db, analisar = sys.argv[1], sys.argv[2] == "1"
c = sqlite3.connect(db, timeout=20)
c.execute("PRAGMA busy_timeout=15000")
try:
    n = c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if analisar:
        c.execute("ANALYZE")
    c.commit()
    print(f"[manut-diaria] ✓ wal_checkpoint={n}" + (" + ANALYZE ok" if analisar else ""))
except Exception as e:
    print(f"[manut-diaria] ⚠️ {str(e)[:80]}")
finally:
    c.close()
PY
