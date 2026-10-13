# -*- coding: utf-8 -*-
"""Coletado NÃO é o mesmo que utilizável — o terceiro estado da cobertura.

A coleta de junho/2026 do SIAFE 1 gravou os campos por POSIÇÃO; a tela do SIAFE 1 tem 19 colunas em
ordem diferente das 23 do SIAFE 2. O valor foi parar em `nome_credor`, o nome do credor em `nl`, e
`valor` ficou 0,00. Medido em 2026-08-10: **12.073 linhas da UG 010100 (2016-2023), 100% delas**,
escondendo **R$ 3.414.630.870,53**. O coletor já mapeia por RÓTULO — a cura é RECOLETAR, e para isso
o medidor precisa parar de chamar essas linhas de cobertura.

Duas armadilhas que o teste fixa:
  1. `numero_ob` é a 1ª coluna e foi gravado CERTO mesmo na coleta torta — a amostra de números casa
     e o par passa por "coberto". A checagem tem de vir ANTES do corte de cobertura.
  2. O laço principal só percorre pares que o ESPELHO conhece; três pares (2016-2018) só existem no
     SIAFE e ficavam invisíveis.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.reporting import cobertura_siafe as C


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.executescript("""
      create table ordens_bancarias (ug_codigo text, numero_ob text, data_emissao text, valor real);
      create table ob_orcamentaria_siafe (numero_ob text, ug_emitente text, data_emissao text,
                                          nome_credor text, valor real, exercicio integer);
    """)
    # par TORTO que o espelho conhece: os números casam, mas o nome do credor é moeda
    for i in range(60):
        con.execute("insert into ordens_bancarias values ('010100',?,?,100.0)",
                    (f"2019OB{i:05d}", "01/01/2019"))
        con.execute("insert into ob_orcamentaria_siafe values (?,'010100','01/01/2019','5.363,99',0.0,2019)",
                    (f"2019OB{i:05d}",))
    # par TORTO que SÓ existe no SIAFE
    for i in range(40):
        con.execute("insert into ob_orcamentaria_siafe values (?,'010100','01/01/2016','1.229,60',0.0,2016)",
                    (f"2016OB{i:05d}",))
    # par SÃO: nome de credor é nome
    for i in range(60):
        con.execute("insert into ordens_bancarias values ('220100',?,'01/01/2024',100.0)",
                    (f"2024OB{i:05d}",))
        con.execute("insert into ob_orcamentaria_siafe values (?,'220100','01/01/2024','ALFA LTDA',100.0,2024)",
                    (f"2024OB{i:05d}",))
    con.commit(); con.close()
    return str(p)


def _por_estado(db):
    m = C.medir(db=db)
    return {(p["ug"], p["exercicio"]): p for p in m["parciais"]}


def test_par_deslocado_nao_conta_como_coberto(db):
    """Ainda que TODOS os números de OB casem com o espelho."""
    p = _por_estado(db)[("010100", "2019")]
    assert p["estado"] == "deslocado"
    assert p["obs_deslocadas"] == p["obs_siafe"] == 60


def test_par_deslocado_que_so_existe_no_SIAFE_tambem_aparece(db):
    p = _por_estado(db)[("010100", "2016")]
    assert p["estado"] == "deslocado" and p["so_no_siafe"] is True


def test_par_sao_nao_e_marcado(db):
    assert ("220100", "2024") not in _por_estado(db)


def test_traz_o_comando_de_recoleta(db):
    p = _por_estado(db)[("010100", "2019")]
    assert "--por-ug 010100" in p["recoletar"] and "--exercicio 2019" in p["recoletar"]
