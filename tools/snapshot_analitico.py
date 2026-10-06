#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""snapshot_analitico — cópia consistente do compliance.db para as leituras ANALÍTICAS (DuckDB).

POR QUE EXISTE (medido 10/09/2026): o `sqlite_scanner` do DuckDB abre e fecha o arquivo a cada consulta;
como lock POSIX é por (pid, inode), cada `close()` dele solta TODOS os locks do processo do servidor
naquele arquivo — a guardiã do WAL e as transações em curso ficam sem lock (`/proc/locks` do servidor:
zero entradas). Sentinela não resolve (reproduzido em `tests/test_conexao_guardia_do_wal.py`). A cura é
o DuckDB nunca tocar o INODE vivo: lê uma cópia (`data/compliance_analitico.db`), feita com a API de
backup do SQLite (consistente, sem travar escritores). Análises (cartel, rodízio, calibração) toleram
um dia de atraso; a integridade do banco vivo, não.

Uso: PYTHONPATH=. .venv/bin/python -m tools.snapshot_analitico   (cruzador 23:00 · nice/ionice)
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
ORIGEM = _REPO / "data" / "compliance.db"
DESTINO = _REPO / "data" / "compliance_analitico.db"


def snapshot(origem: Path = ORIGEM, destino: Path = DESTINO, paginas: int = 4096) -> dict:
    """Backup em lotes de páginas (cede o lock entre lotes); grava em .tmp e troca por os.replace."""
    tmp = destino.with_suffix(".db.tmp")
    for f in (tmp, tmp.with_name(tmp.name + "-wal"), tmp.with_name(tmp.name + "-shm")):
        f.unlink(missing_ok=True)
    t0 = time.time()
    src = sqlite3.connect(f"file:{origem}?mode=ro", uri=True, timeout=120)
    dst = sqlite3.connect(str(tmp))
    try:
        src.backup(dst, pages=paginas, sleep=0.05)
        dst.execute("PRAGMA journal_mode=DELETE")   # cópia é só leitura: sem -wal/-shm para ninguém apagar
        dst.commit()
    finally:
        dst.close(); src.close()
    os.replace(tmp, destino)
    return {"ok": True, "bytes": destino.stat().st_size, "segundos": round(time.time() - t0, 1), "destino": str(destino)}


def main() -> int:
    if not ORIGEM.exists():
        print(f"[snapshot] origem ausente: {ORIGEM}"); return 1
    r = snapshot()
    print(f"[snapshot] {r['bytes'] / 1e9:.2f} GB em {r['segundos']} s → {r['destino']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
