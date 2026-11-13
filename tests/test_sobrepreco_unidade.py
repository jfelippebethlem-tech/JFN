# -*- coding: utf-8 -*-
"""Aba Sobrepreço — só compara a MESMA unidade e apresentação; mostra grupo, fonte e conferência.

Pedido do dono (2026-11-13): "galão de água é diferente de copinho de água [...] o sistema
precisa saber individualizar tudo e isolar os preços pela mesma unidade de medida".
Sintéticos (repositório público).
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import verificacao_pncp as V
from compliance_agent.cruzamentos_intel import sobrepreco

_DDL = """CREATE TABLE pncp_resultado (certame TEXT, item INTEGER, orgao_cnpj TEXT,
    orgao_nome TEXT, unidade_nome TEXT, uf TEXT, municipio TEXT, modalidade INTEGER, objeto TEXT,
    data_pub TEXT, fornecedor_cnpj TEXT, fornecedor_nome TEXT, ordem_classificacao INTEGER,
    item_descricao TEXT, unidade_medida TEXT, valor_unitario REAL, quantidade REAL)"""
CERT = "12345678000199-1-{:06d}/2025"


def _db(tmp_path, linhas):
    p = str(tmp_path / "s.db")
    con = sqlite3.connect(p)
    con.execute(_DDL)
    for i, (desc, un, vu) in enumerate(linhas):
        con.execute("INSERT INTO pncp_resultado VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)",
                    (CERT.format(i + 1), 1, "", f"ORGAO {i % 4}", f"ORGAO {i % 4}", "RJ", "",
                     6, "", "2025-03-01", f"{i:014d}", f"FORN {i}", desc, un, vu, 10))
    con.commit()
    con.close()
    return p


def test_galao_caro_nao_vira_sobrepreco_contra_copinho(tmp_path):
    """5 copos a ~R$ 0,60 e 5 galões a ~R$ 10: antes eram o mesmo 'Água mineral'."""
    linhas = [("Água mineral", "Copo 200 ML", p) for p in (0.5, 0.55, 0.6, 0.62, 0.7)] + \
             [("Água mineral", "Galão 20 L", p) for p in (8, 9, 10, 11, 12)]
    d = sobrepreco(db_path=_db(tmp_path, linhas), esfera=None, verificacao={})
    assert d["n"] == 0 and d["grupos_comparaveis"] == 2


def test_caixa_registrada_como_unidade_e_salto_nao_sobrepreco(tmp_path):
    """Ampola a R$ 140 contra ampolas a R$ 0,2 — preço de caixa lançado como ampola."""
    linhas = [("Água destilada", "Ampola 10 ML", p) for p in (0.15, 0.18, 0.2, 0.21, 0.25, 0.3)]
    linhas.append(("Água destilada", "Ampola 10 ML", 140.0))
    d = sobrepreco(db_path=_db(tmp_path, linhas), esfera=None, verificacao={})
    assert d["n"] == 0
    assert d["indeterminados"]["n_discrepancias_de_salto"] == 1
    disc = d["indeterminados"]["discrepancias_de_salto"][0]
    assert disc["preco"] == 140.0 and disc["link_pncp"].startswith("https://pncp.gov.br/app/")


def test_achado_traz_grupo_unidade_link_e_estado(tmp_path):
    linhas = [("Caneta esferográfica azul", "Unidade", p) for p in (1.0, 1.1, 0.9, 1.0, 1.05)]
    linhas.append(("Caneta esferográfica azul", "Caixa 10,00 UN", 30.0))   # R$ 3,00/un
    db = _db(tmp_path, linhas)
    d = sobrepreco(db_path=db, esfera=None, verificacao={})
    assert d["n"] == 1
    a = d["achados"][0]
    assert a["preco"] == 30.0 and a["preco_normalizado"] == pytest.approx(3.0)
    assert a["fator_unidade"] == 10 and a["unidade_normalizada"] == "unidade"
    assert a["razao"] == pytest.approx(3.0 / 1.025, abs=0.05)   # mediana de 6 = 1,025
    assert a["verificacao"] == V.PENDENTE
    assert a["link_pncp"] == "https://pncp.gov.br/app/editais/12345678000199/2025/6"
    g = a["grupo_comparacao"]
    assert g["n"] == 6 and g["dispersao_p90_p10"] <= 4 and g["amostra"]


def test_item_sem_unidade_sai_da_conta(tmp_path):
    linhas = [("Caneta esferográfica azul", "Unidade", p) for p in (1.0, 1.1, 0.9, 1.0, 1.05)]
    linhas.append(("Caneta esferográfica azul", "", 3.0))
    d = sobrepreco(db_path=_db(tmp_path, linhas), esfera=None, verificacao={})
    assert d["n"] == 0
    assert any("unidade de medida" in m["motivo"] for m in d["indeterminados"]["por_motivo"])


# ── conferência na fonte primária (função pura) ────────────────────────────

_ESP = {"descricao": "Envelope", "unidade": "Unidade", "quantidade": 700,
        "valor_unitario": 82.5, "fornecedor_cnpj": "11.111.111/0001-11"}


def test_comparar_confere():
    est, div, _ = V.comparar(_ESP, {"descricao": "Envelope", "unidadeMedida": "Unidade ",
                                    "quantidade": 700.0},
                             [{"niFornecedor": "11111111000111", "valorUnitarioHomologado": 82.5}])
    assert est == V.VERIFICADO and div == []


def test_comparar_aponta_divergencia_de_unidade_e_preco():
    est, div, _ = V.comparar(_ESP, {"descricao": "Envelope", "unidadeMedida": "Caixa",
                                    "quantidade": 700.0},
                             [{"niFornecedor": "11111111000111", "valorUnitarioHomologado": 8.25}])
    assert est == V.DIVERGENTE and len(div) == 2


def test_resultado_cancelado_nao_confere():
    est, div, _ = V.comparar(_ESP, {"descricao": "Envelope", "unidadeMedida": "Unidade",
                                    "quantidade": 700.0},
                             [{"niFornecedor": "11111111000111", "valorUnitarioHomologado": 82.5,
                               "dataCancelamento": "2025-05-01"}])
    assert est == V.DIVERGENTE


def test_link_pncp_invalido_e_none():
    assert V.link_pncp("lixo") is None and V.link_pncp(None) is None
