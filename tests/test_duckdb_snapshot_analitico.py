# -*- coding: utf-8 -*-
"""DuckDB lê a cópia analítica, nunca o inode vivo (10/09/2026): o sqlite_scanner abre/fecha o arquivo a cada
consulta e cada close() solta TODOS os locks POSIX do processo naquele inode — inclusive os da guardiã."""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest

from compliance_agent.duckdb_util import escolher_db


def test_escolher_db_prefere_snapshot_fresco_e_cai_para_o_vivo_com_motivo(tmp_path):
    snap = tmp_path / "compliance_analitico.db"
    assert escolher_db(None, analitico=str(snap))[1] == "vivo: snapshot ausente"
    snap.write_bytes(b"x")
    agora = time.time()
    assert escolher_db(None, analitico=str(snap), agora=agora) == (str(snap), "snapshot")
    assert escolher_db(None, analitico=str(snap), idade_max_h=1, agora=agora + 3 * 3600)[1].startswith("vivo: snapshot com")
    assert escolher_db("/outro/banco.db", analitico=str(snap)) == ("/outro/banco.db", "pedido")


@pytest.mark.skipif(not Path("/proc/locks").exists(), reason="precisa de /proc/locks (Linux)")
def test_duckdb_na_copia_nao_solta_os_locks_do_banco_vivo(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    from compliance_agent.database import guarda_wal
    vivo = tmp_path / "compliance.db"
    con = sqlite3.connect(vivo); con.execute("PRAGMA journal_mode=WAL"); con.execute("CREATE TABLE t (x)"); con.execute("INSERT INTO t VALUES (1)"); con.commit(); con.close()
    copia = tmp_path / "compliance_analitico.db"
    src = sqlite3.connect(vivo); dst = sqlite3.connect(copia); src.backup(dst); dst.close(); src.close()

    def locks(ino):
        me = str(os.getpid())
        return [l for l in Path("/proc/locks").read_text().splitlines() if l.split()[4] == me and l.split()[5].endswith(f":{ino}")]
    guarda_wal.soltar()   # outro teste pode ter deixado a guardiã aberta (segurar é idempotente)
    try:
        assert guarda_wal.segurar(vivo)
        ino = (tmp_path / "compliance.db-shm").stat().st_ino
        assert locks(ino), "guardiã sem lock no -shm"
        d = duckdb.connect(); d.execute("INSTALL sqlite; LOAD sqlite;")
        d.execute(f"ATTACH '{copia}' AS db (TYPE sqlite, READ_ONLY);"); d.execute("SELECT count(*) FROM db.t").fetchall(); d.close()
        assert locks(ino), "consultar a CÓPIA não pode soltar os locks do banco vivo"
        d = duckdb.connect(); d.execute("INSTALL sqlite; LOAD sqlite;")
        d.execute(f"ATTACH '{vivo}' AS db (TYPE sqlite, READ_ONLY);"); d.execute("SELECT count(*) FROM db.t").fetchall(); d.close()
        assert not locks(ino), "controle: consultar o VIVO solta os locks (é por isso que existe a cópia)"
    finally:
        guarda_wal.soltar()
