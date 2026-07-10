# -*- coding: utf-8 -*-
"""Task 2 — roster de deputados federais RJ."""
from compliance_agent.emendas import camara
from compliance_agent.emendas import db as edb


def test_norm_nome():
    assert camara.norm_nome("Altineu Côrtes ") == "ALTINEU CORTES"
    assert camara.norm_nome("Chris  Tonietto") == "CHRIS TONIETTO"


def test_gravar_roster_dedup_por_id(tmp_path):
    con = edb.conectar(tmp_path / "t.db"); edb.init_schema(con)
    deps = [{"id": 1, "nome": "Fulano", "siglaPartido": "XX", "idLegislatura": 56},
            {"id": 1, "nome": "Fulano", "siglaPartido": "XX", "idLegislatura": 57}]
    n = camara.gravar_roster(con, deps)
    assert n == 1
    row = con.execute("select legislaturas from deputados_federais_rj where id_camara=1").fetchone()
    assert row[0] == "56,57"
