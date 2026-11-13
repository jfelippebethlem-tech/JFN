# -*- coding: utf-8 -*-
"""caro_e_suspeito — dossiê automático: paga muito acima da mediana + fornecedor suspeito (indep.)."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import comparador_precos as CP


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE pncp_resultado (item_descricao TEXT, unidade_medida TEXT, valor_unitario REAL,
        quantidade REAL, orgao_nome TEXT, unidade_nome TEXT, municipio TEXT, fornecedor_nome TEXT,
        fornecedor_cnpj TEXT, ordem_classificacao INTEGER, data_pub TEXT, certame TEXT);
    CREATE TABLE sancoes_federais (cpf_cnpj TEXT, nome TEXT, cadastro TEXT, categoria TEXT,
        data_inicio TEXT, data_fim TEXT, orgao TEXT, uf TEXT, fundamentacao TEXT);
    CREATE TABLE fantasma_score (cnpj TEXT PRIMARY KEY, classificacao TEXT);
    """)
    ins = ("INSERT INTO pncp_resultado (item_descricao, unidade_medida, valor_unitario, quantidade, "
           "orgao_nome, unidade_nome, municipio, fornecedor_nome, fornecedor_cnpj, "
           "ordem_classificacao, data_pub, certame) VALUES (?,?,?,?,?,?,?,?,?,1,?,?)")
    SANC = "99999999000199"
    LIMPO = "11111111000111"
    rows = [
        # "Sonda" a ~10 em 5 compras; um órgão paga 35 (3,4×) a fornecedor SANCIONADO à época.
        # (Antes o caso era 100 = 10×; com a base homogênea de 2026-11-13 um salto ≥4× é
        # unidade/produto diferente e sai como INDETERMINADO — não vira dossiê.)
        ("Sonda Nasogastrica", "UN", 10.0, 5, "A", "A", "RJ", "FORN OK", LIMPO, "2025-01-01", "c1"),
        ("Sonda Nasogastrica", "UN", 11.0, 5, "B", "B", "RJ", "FORN OK", LIMPO, "2025-02-01", "c2"),
        ("Sonda Nasogastrica", "UN", 9.0, 5, "C", "C", "RJ", "FORN OK", LIMPO, "2025-03-01", "c3"),
        ("Sonda Nasogastrica", "UN", 10.0, 5, "A", "A", "RJ", "FORN OK", LIMPO, "2025-01-05", "c5"),
        ("Sonda Nasogastrica", "UN", 10.0, 5, "B", "B", "RJ", "FORN OK", LIMPO, "2025-01-06", "c6"),
        ("Sonda Nasogastrica", "UN", 35.0, 5, "D", "D", "RJ", "SUSPEITA LTDA", SANC, "2025-04-01", "c4"),
        # "Gaze" cara (3,5×) mas fornecedor LIMPO → NÃO entra no dossiê (fica no sobrepreço puro)
        ("Gaze", "UN", 1.0, 5, "A", "A", "RJ", "FORN OK", LIMPO, "2025-01-01", "g1"),
        ("Gaze", "UN", 1.0, 5, "B", "B", "RJ", "FORN OK", LIMPO, "2025-02-01", "g2"),
        ("Gaze", "UN", 1.0, 5, "C", "C", "RJ", "FORN OK", LIMPO, "2025-03-01", "g3"),
        ("Gaze", "UN", 1.1, 5, "A", "A", "RJ", "FORN OK", LIMPO, "2025-03-05", "g5"),
        ("Gaze", "UN", 0.9, 5, "B", "B", "RJ", "FORN OK", LIMPO, "2025-03-06", "g6"),
        ("Gaze", "UN", 3.5, 5, "D", "D", "RJ", "FORN OK", LIMPO, "2025-04-01", "g4"),
    ]
    con.executemany(ins, rows)
    con.execute("INSERT INTO sancoes_federais VALUES (?,?,?,?,?,?,?,?,?)",
                (SANC, "SUSPEITA", "CEIS", "Impedimento/proibição de contratar com prazo determinado", "2024-01-01", "2027-01-01", "Controladoria-Geral do Estado do Rio de Janeiro", "RJ", ""))
    con.commit()
    con.close()
    monkeypatch.setattr("compliance_agent.cruzamentos_intel.ler_cache_intel", lambda n: None)
    return p


def test_dossie_cruza_caro_com_sancionado(db):
    d = CP.caro_e_suspeito(db_path=db, esfera='todas', fator=3.0, min_certames=3)
    assert d["ok"] is True and d["n"] == 1 and d["n_sancionada"] == 1
    a = d["achados"][0]
    assert a["fornecedor_cnpj"] == "99999999000199"
    # mediana de [9,10,10,10,11,35] = 10 → 35/10 = 3,5
    assert a["vs_mediana"] == pytest.approx(3.5, abs=0.1) and a["preco"] == 35.0
    assert any(s["sinal"] == "sancionada" for s in a["sinais"])
    assert "Sonda" in a["item"]


def test_caro_mas_fornecedor_limpo_nao_entra(db):
    d = CP.caro_e_suspeito(db_path=db, esfera='todas', fator=3.0, min_certames=3)
    # a Gaze cara (12×) tem fornecedor limpo → não aparece no dossiê
    assert all("Gaze" not in a["item"] for a in d["achados"])


def test_fator_alto_filtra(db):
    d = CP.caro_e_suspeito(db_path=db, esfera='todas', fator=50.0, min_certames=3)
    assert d["n"] == 0                      # 3,5× não passa do fator 50×


def test_ressalva_fontes_independentes(db):
    d = CP.caro_e_suspeito(db_path=db, esfera='todas')
    assert "INDEPENDENTES" in d["ressalva"] and "Indício" in d["ressalva"]


def _sancao(db, inicio, fim, orgao="Controladoria-Geral do Estado do Rio de Janeiro", uf="RJ"):
    con = sqlite3.connect(db)
    con.execute("DELETE FROM sancoes_federais")
    con.execute("INSERT INTO sancoes_federais VALUES (?,?,?,?,?,?,?,?,?)",
                ("99999999000199", "SUSPEITA", "CEIS",
                 "Impedimento/proibição de contratar com prazo determinado", inicio, fim, orgao,
                 uf, ""))
    con.commit()
    con.close()


def test_sancao_posterior_a_compra_nao_e_sancionada(db):
    """Revisão D6 (2026-11-13): 0 de 5 'sancionadas' do card estavam sancionadas na data."""
    _sancao(db, "2026-03-02", "2028-01-01")
    d = CP.caro_e_suspeito(db_path=db, esfera='todas', fator=3.0, min_certames=3)
    assert d["n_sancionada"] == 0
    sinais = [s["sinal"] for a in d["achados"] for s in a["sinais"]]
    assert "sancionada" not in sinais and "sancionada_depois" in sinais


def test_sancao_de_outro_ente_nao_veda(db):
    """Impedimento aplicado por outro Estado não veda contrato do Estado do RJ."""
    _sancao(db, "2024-01-01", "2027-01-01", orgao="Secretaria de Estado da Bahia", uf="BA")
    d = CP.caro_e_suspeito(db_path=db, esfera='todas', fator=3.0, min_certames=3)
    assert d["n_sancionada"] == 0
