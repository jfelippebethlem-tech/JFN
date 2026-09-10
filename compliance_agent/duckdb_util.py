# -*- coding: utf-8 -*-
"""
DuckDB sobre o SQLite do JFN — acelera as queries analíticas pesadas (agregações sobre 1,1M Ordens Bancárias)
sem mover dado. O DuckDB ataca o próprio `compliance.db` em modo READ_ONLY (sqlite scanner), então não há
duplicação nem risco de escrita. Use para rankings/HHI/grafos; o caminho de escrita continua no SQLAlchemy/sqlite3.

    from compliance_agent.duckdb_util import conectar
    con = conectar()
    df = con.execute("SELECT ... FROM db.ordens_bancarias ...").fetchdf()

Tabelas ficam sob o schema `db.` (ex.: `db.ordens_bancarias`, `db.contratos_tcerj`).
"""
from __future__ import annotations

import os

_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DB = os.environ.get("JFN_DB", os.path.join(_BASE, "data", "compliance.db"))


# Terceira biblioteca SQLite do servidor (sqlite_scanner). Fechar a conexão DuckDB fecha o `-shm`
# e solta os locks POSIX das OUTRAS bibliotecas do mesmo processo (guardiã apsw + stdlib) — ver
# guarda_wal._SENTINELA_STDLIB. Uma conexão anexada mantida para sempre evita esse fechamento.
_SENTINELA = {}


def conectar(db: str | None = None):
    """Conexão DuckDB com o SQLite do JFN anexado como schema `db` (READ_ONLY). Reutilizável e barata."""
    import duckdb
    alvo = db or _DB
    if alvo not in _SENTINELA:
        try:
            s = duckdb.connect()
            s.execute("INSTALL sqlite; LOAD sqlite;")
            s.execute(f"ATTACH '{alvo}' AS db (TYPE sqlite, READ_ONLY);")
            s.execute("SELECT 1 FROM db.sqlite_master LIMIT 1")
            _SENTINELA[alvo] = s
        except Exception:  # noqa: BLE001 — sentinela é proteção, nunca motivo de falha
            _SENTINELA[alvo] = None
    con = duckdb.connect()
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{db or _DB}' AS db (TYPE sqlite, READ_ONLY);")
    con.execute("PRAGMA threads=4;")
    return con
