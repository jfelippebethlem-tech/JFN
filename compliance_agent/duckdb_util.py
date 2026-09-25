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


# O sqlite_scanner do DuckDB abre e fecha o arquivo a cada consulta; cada close() solta TODOS os locks
# POSIX do processo naquele inode (guardiã do WAL inclusive) — medido no servidor vivo em 10/09/2026, e a
# "sentinela" permanente NÃO evita (reproduzido em tests/test_conexao_guardia_do_wal.py). Por isso o
# DuckDB lê a CÓPIA analítica (tools/snapshot_analitico, cruzador 23:00), nunca o inode vivo. Se a cópia
# não existe ou está velha demais, cai para o vivo e AVISA — é o caso degradado, não o normal.
_DB_ANALITICO = os.environ.get("JFN_DB_ANALITICO", os.path.join(_BASE, "data", "compliance_analitico.db"))
_IDADE_MAX_H = float(os.environ.get("JFN_DB_ANALITICO_IDADE_H", "36"))


def escolher_db(db: str | None, analitico: str = _DB_ANALITICO, idade_max_h: float = _IDADE_MAX_H, agora: float | None = None) -> tuple[str, str]:
    """(caminho, motivo): 'snapshot' quando a cópia existe e é fresca; senão o pedido/vivo com o porquê."""
    import time
    if db and os.path.abspath(db) != os.path.abspath(_DB):
        return db, "pedido"
    try:
        idade_h = ((agora or time.time()) - os.path.getmtime(analitico)) / 3600
    except OSError:
        return _DB, "vivo: snapshot ausente"
    if idade_h > idade_max_h:
        return _DB, f"vivo: snapshot com {idade_h:.0f} h"
    return analitico, "snapshot"


def conectar(db: str | None = None):
    """Conexão DuckDB com o SQLite do JFN anexado como schema `db` (READ_ONLY). Reutilizável e barata."""
    import duckdb
    import logging
    alvo, motivo = escolher_db(db)
    if motivo.startswith("vivo"):
        logging.getLogger(__name__).warning("duckdb no banco VIVO (%s) — os locks do processo caem a cada consulta; rode tools/snapshot_analitico", motivo)
    con = duckdb.connect()
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{alvo}' AS db (TYPE sqlite, READ_ONLY);")
    con.execute("PRAGMA threads=4;")
    return con
