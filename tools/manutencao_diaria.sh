#!/bin/bash
# Manutenção DIÁRIA leve da compliance.db (auditoria 2026-06-18): ANALYZE (planner escolhe os
# índices certos após ingestões diárias de centenas de milhares de linhas — OB/folha/doações) +
# wal_checkpoint(TRUNCATE) para o WAL não crescer entre os VACUUMs semanais. NÃO faz VACUUM (caro;
# segue no semanal). VM-safe: ionice idle + nice 19; barato (segundos). Adia se a base estiver em uso pesado.
cd /home/ubuntu/JFN || exit 1
DB=data/compliance.db
# load-guard: se a VM estiver carregada (sweep pesado), pula esta rodada (não compete)
L=$(awk '{print int($1)}' /proc/loadavg)
[ "${L:-0}" -ge 3 ] && { echo "[manut-diaria] load=$L alto — pulando"; exit 0; }
ionice -c3 nice -n19 .venv/bin/python - "$DB" <<'PY'
import sqlite3, sys
db = sys.argv[1]
c = sqlite3.connect(db, timeout=20)
c.execute("PRAGMA busy_timeout=15000")
try:
    n = c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    c.execute("ANALYZE")
    c.commit()
    print(f"[manut-diaria] ✓ wal_checkpoint={n} + ANALYZE ok")
except Exception as e:
    print(f"[manut-diaria] ⚠️ {str(e)[:80]}")
finally:
    c.close()
PY
