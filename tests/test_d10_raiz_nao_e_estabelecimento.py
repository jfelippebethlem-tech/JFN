# -*- coding: utf-8 -*-
"""Filial não é concorrente: a gravidade da rede está na RAIZ, não no estabelecimento.

O `having` do d10 sempre contou raízes (grupos econômicos), mas a evidência listava CNPJs de 14
dígitos — com filiais. Medido em 2026-08-10: um achado exibia **"30 fornecedores"** para uma pessoa
que está em DUAS raízes; eram 30 estabelecimentos de 2 grupos. Quem lê entende 30 empresas
concorrendo entre si, que é impressão falsa e muito mais grave que o fato. Com a correção, o maior
achado do acervo passou de "30" para **6 grupos**.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.pcrj.pericia_gastos import d10_rede_concorrentes


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
      create table pcrj_contratos (orgao_cnpj text, orgao_nome text, ano integer,
                                   fornecedor_documento text, fornecedor_nome text);
      create table socios_receita (cnpj_basico text, nome_norm text, nome_socio text,
                                   doc_socio text, data_entrada text);
    """)
    return c


def _socio(con, raiz, doc="***111111**"):
    con.execute("insert into socios_receita values (?,?,?,?,?)",
                (raiz, "maria souza", "MARIA SOUZA", doc, "20180101"))


def _contrato(con, cnpj14, nome):
    con.execute("insert into pcrj_contratos values ('99','SMS',2024,?,?)", (cnpj14, nome))


def test_filiais_da_mesma_raiz_nao_inflam_a_rede(con):
    """Duas raízes, uma com matriz + 5 filiais contratando: são 2 grupos e 7 estabelecimentos."""
    _socio(con, "11111111"); _socio(con, "22222222")
    _contrato(con, "11111111000101", "ALFA MATRIZ")
    for i in range(2, 7):
        _contrato(con, f"111111110001{i:02d}", f"ALFA FILIAL {i}")
    _contrato(con, "22222222000101", "BETA")
    con.commit()
    a = d10_rede_concorrentes(con)
    assert len(a) == 1
    e = a[0]["evidencias"]
    assert e["n_grupos"] == 2, "a gravidade é a RAIZ"
    assert e["n_estabelecimentos"] == 7
    assert "em 2 fornecedores" in a[0]["titulo"]


def test_estabelecimentos_saem_declarados_quando_ha_filial(con):
    _socio(con, "11111111"); _socio(con, "22222222")
    _contrato(con, "11111111000101", "ALFA")
    _contrato(con, "11111111000202", "ALFA FILIAL")
    _contrato(con, "22222222000101", "BETA")
    con.commit()
    a = d10_rede_concorrentes(con)[0]
    assert "estabelecimentos, contando filiais" in a["descricao"]


def test_sem_filial_nao_polui_o_texto(con):
    _socio(con, "11111111"); _socio(con, "22222222")
    _contrato(con, "11111111000101", "ALFA")
    _contrato(con, "22222222000101", "BETA")
    con.commit()
    a = d10_rede_concorrentes(con)[0]
    assert "estabelecimentos" not in a["descricao"]
    assert a["evidencias"]["n_grupos"] == a["evidencias"]["n_estabelecimentos"] == 2
