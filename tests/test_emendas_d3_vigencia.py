# -*- coding: utf-8 -*-
"""Sanção que começou DEPOIS da emenda não acusa ninguém.

O d3 cruzava favorecido × sanção sem olhar data e acusava com risco 9. Medido em 2026-08-10 sobre
os 746 pares que casam: **656 (87,9%) têm sanção iniciada depois do ano da emenda**, e o vão não é
de meses — 529 têm 2 anos ou mais, 278 têm 4 ou mais. Mesma lição de
`situacao-cadastral-vigencia-na-data`, onde 78,7% das acusações eram anacrônicas.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.emendas.pericia import d3_favorecido_sancionado


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
      create table emenda_favorecidos (codigo_emenda text, documento_favorecido text,
                                       nome_favorecido text, valor real);
      create table sancoes_federais (cadastro text, cpf_cnpj text, nome text, categoria text,
                                     data_inicio text, data_fim text, orgao text);
      create table emendas (codigo text, ano integer);
    """)
    c.executemany("insert into emendas values (?,?)",
                  [("E2019", 2019), ("E2024", 2024), ("ESEMANO", None)])
    return c


def _favorecido(con, cod, doc="11111111000111", nome="ALFA LTDA"):
    con.execute("insert into emenda_favorecidos values (?,?,?,?)", (cod, doc, nome, 1000.0))


def _sancao(con, doc="11111111000111", ini="2019-01-01", fim="2029-01-01"):
    con.execute("insert into sancoes_federais values ('CEIS',?,'ALFA LTDA','inidônea',?,?,'MEC')",
                (doc, ini, fim))


def _um(con):
    a = d3_favorecido_sancionado(con)
    assert len(a) == 1
    return a[0]


def test_sancao_vigente_na_emenda_e_risco_alto(con):
    _favorecido(con, "E2024"); _sancao(con, ini="2023-01-01", fim="2033-01-01")
    a = _um(con)
    assert a["evidencias"]["vigencia_na_emenda"] == "vigente"
    assert a["risco"] == 9
    assert a["titulo"].startswith("Favorecido sancionado —")


def test_sancao_POSTERIOR_nao_acusa(con):
    """O caso dos 656: emenda de 2019, sanção de 2024. Não some — muda de natureza e de risco."""
    _favorecido(con, "E2019"); _sancao(con, ini="2024-05-01", fim="2034-05-01")
    a = _um(con)
    assert a["evidencias"]["vigencia_na_emenda"] == "posterior"
    assert a["risco"] == 3
    assert "APÓS a emenda" in a["titulo"]
    assert "NÃO é acusação" in a["descricao"]


def test_sancao_ENCERRADA_antes_da_emenda_nao_acusa(con):
    _favorecido(con, "E2024"); _sancao(con, ini="2015-01-01", fim="2018-01-01")
    a = _um(con)
    assert a["evidencias"]["vigencia_na_emenda"] == "encerrada"
    assert a["risco"] == 3


def test_sem_ano_da_emenda_e_INDETERMINADA_nao_confirmacao(con):
    """INDISPONÍVEL ≠ 0 e INDISPONÍVEL ≠ confirmado: sem data, não se afirma vigência."""
    _favorecido(con, "ESEMANO"); _sancao(con)
    a = _um(con)
    assert a["evidencias"]["vigencia_na_emenda"] == "indeterminada"
    assert a["risco"] < 9 and "não apurada" in a["titulo"]


def test_match_por_raiz_de_cnpj_rebaixa(con):
    """Filial/matriz é indício de identidade, não identidade."""
    _favorecido(con, "E2024", doc="11111111000199")
    _sancao(con, doc="11111111000111", ini="2023-01-01", fim="2033-01-01")
    a = _um(con)
    assert a["evidencias"]["match_exato"] is False and a["risco"] == 7


def test_sancao_vigente_mas_NAO_impeditiva_nao_acusa(con):
    """Multa do CNEP e publicação extraordinária são penalidades reais que NÃO vedam contratar.
    Medido: 10 dos 60 vigentes (16,7%) eram desses, saindo com o mesmo risco 9 dos impedimentos."""
    _favorecido(con, "E2024")
    con.execute("insert into sancoes_federais values ('CNEP','11111111000111','ALFA LTDA','Multa',"
                "'2023-01-01','2033-01-01','CGU')")
    a = _um(con)
    assert a["evidencias"]["vigencia_na_emenda"] == "nao_impeditiva"
    assert a["risco"] == 4
    assert "NÃO veda contratar" in a["descricao"]


def test_publicacao_extraordinaria_tambem_nao_impede(con):
    _favorecido(con, "E2024")
    con.execute("insert into sancoes_federais values ('CNEP','11111111000111','ALFA LTDA',"
                "'Publicação extraordinária da decisão condenatória','2023-01-01','2033-01-01','CGU')")
    assert _um(con)["evidencias"]["vigencia_na_emenda"] == "nao_impeditiva"
