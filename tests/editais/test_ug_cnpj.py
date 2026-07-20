# -*- coding: utf-8 -*-
"""Resolvedor UG↔CNPJ (F5.1) — precisão > cobertura: melhor nenhum match que match errado.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/editais/test_ug_cnpj.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.editais.ug_cnpj import resolver

PNCP_DDL = """CREATE TABLE pncp_resultado (certame TEXT, orgao_cnpj TEXT, orgao_nome TEXT,
    uf TEXT, municipio TEXT, modalidade INTEGER, objeto TEXT, data_pub TEXT, item INTEGER,
    fornecedor_cnpj TEXT, fornecedor_nome TEXT, valor_homologado REAL, ordem_classificacao INTEGER,
    porte_fornecedor TEXT, coletado_em TEXT, unidade_codigo TEXT, unidade_nome TEXT,
    item_descricao TEXT, unidade_medida TEXT, valor_unitario REAL, quantidade REAL)"""


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute(PNCP_DDL)
    for cnpj, nome in (
        ("30051023000196", "TRIBUNAL DE CONTAS DO ESTADO DO RIO DE JANEIRO"),
        ("42498600000171", "ESTADO DO RIO DE JANEIRO"),
        ("33540014000157", "UNIVERSIDADE DO ESTADO DO RIO DE JANEIRO"),
        ("00038166000105", "BANCO CENTRAL DO BRASIL"),
        ("30449862000167", "RIO DE JANEIRO ASSEMBLEIA LEGISLATIVA"),
        ("30134050000122", "INSTITUTO DE PREVIDENCIA DA ASSEMBLEIA LEGISLATIVA DO ESTADO DO RIO DE JANEIRO"),
        ("28347520000122", "INSTITUTO DE TERRAS E CARTOGRAFIA DO ESTADO DO RIO DE JANEIRO ITERJ"),
    ):
        con.execute("INSERT INTO pncp_resultado (certame, orgao_cnpj, orgao_nome) VALUES (?,?,?)",
                    (f"{cnpj}-1-000001/2026", cnpj, nome))
    con.commit()
    con.close()
    yield p


def test_nome_exato_vence_o_ente_generico(db):
    r = resolver("020100", "Tribunal de Contas do Estado do Rio de Janeiro", db_path=db)
    assert r and r["cnpj"] == "30051023000196" and r["metodo"] == "nome_exato"


def test_acronimo_uerj(db):
    r = resolver("404300", "UERJ", db_path=db)
    assert r and r["cnpj"] == "33540014000157" and r["metodo"] == "acronimo"


def test_sigla_no_nome_exige_ancora_da_esfera(db):
    # "CENTRAL" casaria com BANCO CENTRAL DO BRASIL (federal) — a âncora "Rio de Janeiro" veta (FP real)
    assert resolver("317200", "CENTRAL", db_path=db) is None


def test_sigla_iterj_com_ancora(db):
    r = resolver("133100", "ITERJ", db_path=db)
    assert r and r["cnpj"] == "28347520000122" and r["metodo"] == "sigla_no_nome"


def test_contencao_desempata_pelo_mais_proximo(db):
    # ALERJ por extenso é contido tanto pelo nome da ALERJ (Δ=1 token) quanto pelo do fundo de
    # previdência dela (Δ=2) — vence o mais próximo; não vira ambíguo
    r = resolver("010100", "Assembleia Legislativa do Estado do Rio de Janeiro", db_path=db)
    assert r and r["cnpj"] == "30449862000167" and r["metodo"] == "contencao"


def test_sem_match_honesto(db):
    assert resolver("999999", "FUNDACAO INEXISTENTE XPTO", db_path=db) is None