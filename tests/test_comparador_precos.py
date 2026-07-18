# -*- coding: utf-8 -*-
"""comparador_precos — quem paga mais/menos pelo mesmo item; eficiência de órgão/fornecedor."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import comparador_precos as CP


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE pncp_resultado (item_descricao TEXT, unidade_medida TEXT,
        valor_unitario REAL, quantidade REAL, orgao_nome TEXT, unidade_nome TEXT,
        fornecedor_nome TEXT, fornecedor_cnpj TEXT, ordem_classificacao INTEGER, data_pub TEXT,
        certame TEXT)""")
    ins = ("INSERT INTO pncp_resultado (item_descricao, unidade_medida, valor_unitario, quantidade, "
           "orgao_nome, unidade_nome, fornecedor_nome, fornecedor_cnpj, ordem_classificacao, "
           "certame) VALUES (?,?,?,?,?,?,?,?,1,?)")
    rows = [
        # "Locacao de Veiculo" comprada por 3 órgãos: A barato (10), B mediana (20), C caro (100)
        ("Locacao de Veiculo Leve", "UN", 10.0, 5, "ORG A", "ORG A", "FORN X", "11111111000111", "c1"),
        ("Locacao de Veiculo Leve", "UN", 20.0, 5, "ORG B", "ORG B", "FORN Y", "22222222000122", "c2"),
        ("Locacao de Veiculo Leve", "UN", 100.0, 5, "ORG C", "ORG C", "FORN Z", "33333333000133", "c3"),
    ]
    con.executemany(ins, rows)
    con.commit()
    con.close()
    return p


def test_buscar_grupos_casa_termo(db):
    d = CP.buscar_grupos("veiculo locacao", db_path=db, min_compras=3, min_orgaos=2)
    assert d["ok"] is True and d["n"] == 1
    g = d["grupos"][0]
    assert g["n_orgaos"] == 3 and g["mediana"] == 20.0
    assert g["min"] == 10.0 and g["max"] == 100.0 and g["dispersao"] == 10.0


def test_buscar_termo_sem_match(db):
    d = CP.buscar_grupos("medicamento", db_path=db)
    assert d["ok"] is True and d["n"] == 0


def test_comparar_ranqueia_orgaos_por_preco(db):
    grupo = CP.buscar_grupos("veiculo", db_path=db)["grupos"][0]["grupo"]  # chave normalizada
    d = CP.comparar(grupo, db_path=db)
    assert d["ok"] is True and d["mediana_geral"] == 20.0
    # ORG C é o mais caro (100 = 5× a mediana), ORG A o mais barato (10 = 0.5×)
    assert d["orgaos"][0]["nome"] == "ORG C" and d["orgaos"][0]["vs_geral"] == 5.0
    assert d["orgaos"][-1]["nome"] == "ORG A" and d["orgaos"][-1]["vs_geral"] == 0.5
    # fornecedores idem
    assert d["fornecedores"][0]["nome"] == "FORN Z"
    assert d["fornecedores"][0]["id"] == "33333333000133"


def test_comparar_grupo_inexistente(db):
    d = CP.comparar("inexistente", db_path=db)
    assert d["ok"] is False


def test_ranking_orgaos_exige_diversidade_de_itens(db):
    # com min_itens=8 e só 1 item comparável, ninguém entra (evita ranking com 1-2 itens)
    d = CP.ranking_orgaos(db_path=db, min_itens=8)
    assert d["ok"] is True and d["n"] == 0
    # com min_itens=1, os 3 órgãos entram e ORG A é o mais eficiente (0.5×)
    d1 = CP.ranking_orgaos(db_path=db, min_itens=1)
    assert d1["melhores"][0]["nome"] == "ORG A" and d1["melhores"][0]["razao_mediana"] == 0.5
    assert d1["piores"][0]["nome"] == "ORG C"


def test_ressalva_presente(db):
    assert "Indício" in CP.buscar_grupos("x", db_path=db)["ressalva"]
