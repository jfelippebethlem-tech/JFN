# -*- coding: utf-8 -*-
"""VACUUM só quando há o que recuperar.

Medido em 04/11/2026: o compliance.db tem 5,1 GB e 0 páginas livres; o VACUUM semanal recuperava
~2% e, enquanto reescrevia o arquivo, travava toda gravação além dos 60 s de busy_timeout — a coleta
do PNCP morreu assim em 01/11.
"""
import sqlite3

from compliance_agent import manutencao as M


def _db(tmp_path, apagar: bool):
    p = tmp_path / "t.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE t(x TEXT)")
    c.executemany("INSERT INTO t VALUES (?)", [("x" * 500,) for _ in range(4000)])
    c.commit()
    if apagar:
        c.execute("DELETE FROM t WHERE rowid > 1000")   # bloco contínuo: libera páginas inteiras
        c.commit()
    c.close()
    return str(p)


def test_sem_paginas_livres_nao_reescreve(tmp_path):
    r = M.vacuum(_db(tmp_path, apagar=False))
    assert r["pulado"] is True and r["livre_pct"] < 5


def test_com_paginas_livres_reescreve_e_encolhe(tmp_path):
    r = M.vacuum(_db(tmp_path, apagar=True))
    assert r.get("pulado") is not True
    assert r["db_depois"] < r["db_antes"]
