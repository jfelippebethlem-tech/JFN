# -*- coding: utf-8 -*-
"""economia_potencial — quanto os cofres economizariam pagando a mediana; cap anti-artefato."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import comparador_precos as CP


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE pncp_resultado (item_descricao TEXT, unidade_medida TEXT,
        valor_unitario REAL, quantidade REAL, orgao_nome TEXT, unidade_nome TEXT, municipio TEXT,
        fornecedor_nome TEXT, fornecedor_cnpj TEXT, ordem_classificacao INTEGER, data_pub TEXT,
        certame TEXT)""")
    ins = ("INSERT INTO pncp_resultado (item_descricao, unidade_medida, valor_unitario, quantidade, "
           "orgao_nome, unidade_nome, fornecedor_nome, fornecedor_cnpj, ordem_classificacao, certame) "
           "VALUES (?,?,?,?,?,?,?,?,1,?)")
    rows = [
        # Item "Cadeira": mediana 10. Um órgão paga 30 (excesso 20) × 100 unid = R$2.000 de economia.
        ("Cadeira", "UN", 10.0, 10, "A", "A", "F1", "11111111000111", "c1"),
        ("Cadeira", "UN", 10.0, 10, "B", "B", "F1", "11111111000111", "c2"),
        ("Cadeira", "UN", 10.0, 10, "C", "C", "F1", "11111111000111", "c3"),
        ("Cadeira", "UN", 30.0, 100, "D", "D", "F2", "22222222000122", "c4"),
    ]
    con.executemany(ins, rows)
    con.commit()
    con.close()
    return p


def test_economia_soma_excesso_vezes_quantidade(db):
    d = CP.economia_potencial(db_path=db, min_amostra=3, min_orgaos=2, min_certames=3)
    assert d["ok"] is True
    # excesso (30-10) × 100 = 2.000
    assert d["economia_total"] == pytest.approx(2000.0)
    assert d["n_compras_acima_mediana"] == 1
    assert d["por_orgao"][0]["orgao"] == "D" and d["por_orgao"][0]["economia"] == pytest.approx(2000.0)
    assert d["por_fornecedor"][0]["fornecedor_cnpj"] == "22222222000122"


def test_cap_anti_artefato_limita_excesso(tmp_path):
    p = str(tmp_path / "a.db")
    con = sqlite3.connect(p)
    ins = ("INSERT INTO pncp_resultado (item_descricao, unidade_medida, valor_unitario, quantidade, "
           "orgao_nome, unidade_nome, fornecedor_nome, fornecedor_cnpj, ordem_classificacao, certame) "
           "VALUES (?,?,?,?,?,?,?,?,1,?)")
    con.execute("""CREATE TABLE pncp_resultado (item_descricao TEXT, unidade_medida TEXT,
        valor_unitario REAL, quantidade REAL, orgao_nome TEXT, unidade_nome TEXT, municipio TEXT,
        fornecedor_nome TEXT, fornecedor_cnpj TEXT, ordem_classificacao INTEGER, data_pub TEXT,
        certame TEXT)""")
    con.executemany(ins, [
        ("Toner", "UN", 10.0, 2, "A", "A", "F", "11111111000111", "c1"),
        ("Toner", "UN", 10.0, 2, "B", "B", "F", "11111111000111", "c2"),
        ("Toner", "UN", 10.0, 2, "C", "C", "F", "11111111000111", "c3"),
        # artefato: 5000 (500× a mediana 10), qtd 2 → capado em 20× = 200, excesso (200−10)×2=380
        ("Toner", "UN", 5000.0, 2, "D", "D", "F2", "22222222000122", "c4"),
    ])
    con.commit()
    con.close()
    d = CP.economia_potencial(db_path=p, min_amostra=3, min_orgaos=2, min_certames=3, teto_razao=20.0)
    assert d["economia_total"] == pytest.approx(380.0)   # (200 capado − 10) × 2, não (5000−10)×2


def test_ressalva_teto_teorico(db):
    d = CP.economia_potencial(db_path=db)
    assert "teto" in d["ressalva"].lower() and "Indício" in d["ressalva"]
