# -*- coding: utf-8 -*-
"""T1 — schema aditivo do enxame de editais."""
from compliance_agent.editais import db as ed

TABS = {"edital_documento", "edital_clausula", "edital_cluster", "clausula_veredito"}


def test_init_schema_idempotente(tmp_path):
    con = ed.conectar(tmp_path / "t.db")
    ed.init_schema(con); ed.init_schema(con)
    got = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert TABS <= got
