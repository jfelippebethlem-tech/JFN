# -*- coding: utf-8 -*-
"""C1 — schema aditivo do enxame de contratos."""
from compliance_agent.contratos import db as cd

TABS = {"contrato_aditivo", "contrato_dossie", "contrato_parecer", "preco_referencia_cache"}


def test_init_schema_idempotente(tmp_path):
    con = cd.conectar(tmp_path / "t.db")
    cd.init_schema(con); cd.init_schema(con)
    got = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert TABS <= got
