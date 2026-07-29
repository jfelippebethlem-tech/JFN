# -*- coding: utf-8 -*-
"""Concentração por grupo de fato — e as quatro maneiras de o delta mentir.

  1. **Uma pessoa em muitas empresas une o mercado inteiro num grupo só.** Administrador
     profissional e colisão da máscara de CPF (977 de 24.448 documentos carregam mais de um nome)
     produziriam um "grupo" com metade dos fornecedores e um HHI de 1,0 falso.
  2. **Fornecedor sem QSA tratado como grupo de outro.** Ele é grupo de si mesmo, e a fração de
     valor nessa situação tem de sair declarada — o delta é PISO, não teto.
  3. **Medir empenho em vez de OB.** Empenho é valor bruto que pode ser cancelado; concentrar
     empenho não é concentrar dinheiro.
  4. **Ler grupo como ilícito.** Holding, franquia e consórcio são lícitos. O achado é a
     concentração que a medição por CNPJ escondia.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.osint import grupo_economico as G


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE rede_socios_fornecedores(nome_socio TEXT, nome_norm TEXT, "
              "doc_socio TEXT, n_fornecedores INT, cnpjs_basicos TEXT, qualificacoes TEXT, "
              "total_recebido REAL)")
    c.execute("CREATE TABLE ob_orcamentaria_siafe(ug_emitente TEXT, credor TEXT, "
              "nome_credor TEXT, valor REAL, data_emissao TEXT)")
    return c


def _pessoa(c, nome, basicos):
    c.execute("INSERT INTO rede_socios_fornecedores VALUES(?,?,?,?,?,?,?)",
              (nome, nome, "***111222**", len(basicos), ",".join(basicos), "49", 0.0))


def _ob(c, ug, cnpj, valor, nome="EMPRESA", data="15/03/2024"):
    c.execute("INSERT INTO ob_orcamentaria_siafe VALUES(?,?,?,?,?)", (ug, cnpj, nome, valor, data))


# ─────────────────── o delta é o achado ───────────────────────────────────────────────────────

def test_mercado_disperso_por_CNPJ_pode_ser_concentrado_por_GRUPO(con):
    """O caso real: SECID tinha HHI 0,106 por CNPJ e 0,406 por grupo."""
    for i, cnpj in enumerate(("11111111000191", "22222222000192", "33333333000193")):
        _ob(con, "UG1", cnpj, 300.0)
    _ob(con, "UG1", "44444444000194", 100.0)
    _pessoa(con, "DONO COMUM", ["11111111", "22222222", "33333333"])
    r = G.concentracao_da_ug(con, "UG1")
    assert r["hhi_por_cnpj"] < 0.30 < r["hhi_por_grupo"]
    assert r["agrupamento_mudou_a_leitura"] is True
    assert r["n_cnpj"] == 4 and r["n_grupo"] == 2


def test_sem_sociedade_comum_o_delta_e_zero(con):
    for cnpj in ("11111111000191", "22222222000192", "33333333000193"):
        _ob(con, "UG1", cnpj, 100.0)
    r = G.concentracao_da_ug(con, "UG1")
    assert r["delta_hhi"] == 0.0 and r["agrupamento_mudou_a_leitura"] is False


def test_fecho_transitivo_forma_o_grupo(con):
    """A liga B por uma pessoa, B liga C por outra: as três são um grupo de fato."""
    for cnpj in ("11111111000191", "22222222000192", "33333333000193"):
        _ob(con, "UG1", cnpj, 100.0)
    _pessoa(con, "PESSOA X", ["11111111", "22222222"])
    _pessoa(con, "PESSOA Y", ["22222222", "33333333"])
    assert G.concentracao_da_ug(con, "UG1")["n_grupo"] == 1


# ─────────────────── trava 1: pessoa hiperconectada ───────────────────────────────────────────

def test_pessoa_em_empresas_demais_NAO_une_ninguem(con):
    """Administrador profissional uniria o mercado inteiro num grupo só."""
    basicos = [f"{i:08d}" for i in range(1, 41)]
    for b in basicos[:4]:
        _ob(con, "UG1", b + "000199", 100.0)
    _pessoa(con, "CONTADOR DO MERCADO", basicos)
    r = G.concentracao_da_ug(con, "UG1")
    assert r["n_grupo"] == 4, "a pessoa hiperconectada agrupou o que não devia"


def test_limite_de_empresas_por_pessoa_e_declarado(con):
    g = G.montar_grupos(con)
    assert g["max_empresas_por_pessoa"] == G.MAX_EMPRESAS_POR_PESSOA


# ─────────────────── trava 2: cobertura de QSA ────────────────────────────────────────────────

def test_fornecedor_sem_QSA_e_grupo_de_si_mesmo_e_isso_sai_declarado(con):
    _ob(con, "UG1", "11111111000191", 700.0)
    _ob(con, "UG1", "99999999000199", 300.0)
    _pessoa(con, "DONO", ["11111111", "22222222"])
    r = G.concentracao_da_ug(con, "UG1")
    assert r["cobertura_qsa"]["fracao_sem_qsa"] == pytest.approx(0.3)
    assert "PISO" in r["cobertura_qsa"]["nota"]


def test_delta_e_piso_nunca_teto(con):
    """Mais cobertura de QSA só pode revelar MAIS concentração, nunca menos."""
    _ob(con, "UG1", "11111111000191", 500.0)
    _ob(con, "UG1", "22222222000192", 500.0)
    sem = G.concentracao_da_ug(con, "UG1")
    _pessoa(con, "DONO", ["11111111", "22222222"])
    com = G.concentracao_da_ug(con, "UG1")
    assert com["hhi_por_grupo"] >= sem["hhi_por_grupo"]


# ─────────────────── trava 3 e 4: OB e leitura ────────────────────────────────────────────────

def test_credor_pessoa_fisica_fica_fora_da_medida(con):
    """A medida é de concentração de mercado entre PJ; folha e diária não entram."""
    _ob(con, "UG1", "11111111000191", 100.0)
    _ob(con, "UG1", "***123456**", 900.0, nome="SERVIDOR")
    assert G.concentracao_da_ug(con, "UG1")["n_cnpj"] == 1


def test_valor_negativo_ou_zero_nao_entra(con):
    _ob(con, "UG1", "11111111000191", 100.0)
    _ob(con, "UG1", "22222222000192", 0.0)
    assert G.concentracao_da_ug(con, "UG1")["n_cnpj"] == 1


def test_filtro_por_ano_le_a_data_como_TEXTO_DDMMAAAA(con):
    """`data_emissao` do SIAFE é TEXTO DD/MM/AAAA — o ano está nos caracteres 7-10."""
    _ob(con, "UG1", "11111111000191", 100.0, data="15/03/2024")
    _ob(con, "UG1", "22222222000192", 100.0, data="15/03/2023")
    assert G.concentracao_da_ug(con, "UG1", ano="2024")["n_cnpj"] == 1


def test_ressalva_diz_que_grupo_nao_e_ilicito_e_que_OB_e_pagamento(con):
    _ob(con, "UG1", "11111111000191", 100.0)
    r = G.concentracao_da_ug(con, "UG1")
    assert "NÃO é ilícito" in r["ressalva"] and "empenho não é pagamento" in r["ressalva"]


# ─────────────────── estados honestos ─────────────────────────────────────────────────────────

def test_ug_sem_pagamento_a_pj_e_declarada_e_nao_zerada(con):
    assert G.concentracao_da_ug(con, "UG_VAZIA")["estado"] == "sem_pagamento_a_pj"


def test_sem_a_tabela_de_rede_o_agrupamento_declara_o_motivo():
    c = sqlite3.connect(":memory:")
    assert "ausente" in G.montar_grupos(c).get("motivo", "")


def test_ranking_ordena_pelo_DELTA_e_nao_pelo_HHI_absoluto(con):
    # UG A: muito concentrada por CNPJ, sem grupo (delta 0)
    _ob(con, "A", "11111111000191", 900.0)
    for i in range(2, 7):
        _ob(con, "A", f"{i:08d}000199", 20.0)
    # UG B: dispersa por CNPJ, um grupo domina (delta alto)
    for cnpj in ("21111111", "22222222", "23333333", "24444444", "25555555"):
        _ob(con, "B", cnpj + "000199", 200.0)
    _pessoa(con, "DONO B", ["21111111", "22222222", "23333333", "24444444"])
    r = G.ranking(con, minimo_cnpj=5)
    assert r[0]["ug"] == "B", "o ranking premiou HHI absoluto em vez do que o grupo revelou"
