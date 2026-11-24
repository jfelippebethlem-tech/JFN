# -*- coding: utf-8 -*-
"""O4.1 — `dominio.pagamento.ob_paga_sql` É o predicado canônico `cruzamentos_intel._ob_paga` (invariante 1:
pago = OB paga do SIAFE). Paridade nos três schemas que o predicado distingue."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.cruzamentos_intel import _ob_paga
from compliance_agent.dominio.pagamento import ob_paga_sql

SCHEMAS = {
    "antigo": "CREATE TABLE ob_orcamentaria_siafe(numero_ob TEXT, ug_emitente TEXT, status TEXT, valor REAL)",
    "envio": "CREATE TABLE ob_orcamentaria_siafe(numero_ob TEXT, ug_emitente TEXT, status TEXT, status_envio TEXT, valor REAL)",
    "completo": ("CREATE TABLE ob_orcamentaria_siafe(numero_ob TEXT, ug_emitente TEXT, status TEXT, status_envio TEXT,"
                 " tipo_regularizacao TEXT, valor REAL); CREATE TABLE ob_reemitida(ob TEXT, ug TEXT)"),
}


@pytest.mark.parametrize("schema", sorted(SCHEMAS))
@pytest.mark.parametrize("alias", ["", "o"])
def test_ob_paga_sql_identico_ao_canonico(schema, alias):
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMAS[schema])
    assert ob_paga_sql(con, alias) == _ob_paga(con, alias)
    assert ob_paga_sql(con) == _ob_paga(con)


def test_ob_paga_sql_filtra_de_verdade():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMAS["completo"])
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES(?,?,?,?,?,?)", [
        ("2026OB00001", "080001", "Contabilizado", "Enviado ao Banco", "", 10.0),
        ("2026OB00002", "080001", "Anulado", "", "", 20.0),
        ("2026OB00003", "080001", "Contabilizado", "Erro no Pagamento", "", 40.0),
        ("2026OB00004", "080001", "Contabilizado", "Enviado Manualmente", "Pagamento Complementar", 80.0),
        ("", "080001", "Contabilizado", "", "", 160.0),
    ])
    assert con.execute(f"SELECT SUM(valor) FROM ob_orcamentaria_siafe WHERE {ob_paga_sql(con)}").fetchone()[0] == 10.0
