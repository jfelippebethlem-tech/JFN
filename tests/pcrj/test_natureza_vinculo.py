# -*- coding: utf-8 -*-
"""Natureza do vínculo (clareza 'é nomeado?' — pedido do dono 2026-07-11): a classificação
pessoa a pessoa nunca chama efetivo/aposentado de 'nomeado' e declara quando a fonte não informa."""
import sqlite3

import pytest

from compliance_agent.pcrj import pericia_beneficios as pb


# ── Câmara: o campo "vínculo" decide sozinho ──────────────────────────────────────────
@pytest.mark.parametrize("vinculo,curta,nomeado", [
    ("Livre Nomeação e Exoneração", "NOMEADO", True),
    ("Requisitados com Cargo", "REQUISITADO", False),
    ("Requisitados sem Cargo", "REQUISITADO", False),
    ("ANALISTA LEGISLATIVO - ESPECIALIDADE: DIREITO", "EFETIVO", False),
    ("PROCURADOR DA CMRJ", "EFETIVO", False),
    ("", "NÃO INFORMADO", None),
])
def test_natureza_camara(vinculo, curta, nomeado):
    c, det, n = pb._natureza_camara(vinculo)
    assert c == curta and n is nomeado
    assert det  # sempre explica de onde veio


# ── cargo em comissão × carreira (padrão canônico + vetos de falso positivo) ─────────
@pytest.mark.parametrize("cargo,eh", [
    ("ESPECIAL", True),
    ("ESPECIAL RPA", True),
    ("ASSESSOR III", True),
    ("ASSESSOR ESPECIAL DA PRESIDÊNCIA", True),
    ("AGENTE DE APOIO A EDUCACAO ESPECIAL", False),   # falso positivo conhecido — vetado
    ("ESTAGIÁRIO DE EDUCAÇÃO ESPECIAL", False),
    ("Analista Legislativo - Especialidade Enfermagem", False),
    ("GUARDA MUNICIPAL", False),
    ("PROFESSOR II", False),
    ("", False),
])
def test_cargo_comissionado(cargo, eh):
    assert pb._cargo_comissionado(cargo) is eh


# ── Prefeitura: tipo de folha + cargo da consulta nominal ────────────────────────────
@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE pcrj_prefeitura_consulta (nome_norm TEXT, encontrado INT, cargo TEXT)")
    c.execute("CREATE TABLE pcrj_comissionado_candidato (nome_norm TEXT, cargo_pcrj TEXT)")
    c.execute("INSERT INTO pcrj_prefeitura_consulta VALUES ('fulano comissao', 1, 'ESPECIAL')")
    c.execute("INSERT INTO pcrj_prefeitura_consulta VALUES ('beltrano carreira', 1, 'GUARDA MUNICIPAL')")
    return c


def test_prefeitura_previdencia(con):
    c, det, n = pb._natureza_prefeitura(con, "x", {"PREVNORMAL", "PREVSUPLEMENTO"})
    assert c == "APOSENT./PENSÃO" and n is False and "previdenci" in det


def test_prefeitura_estagio_tsve(con):
    c, _, n = pb._natureza_prefeitura(con, "x", {"TSVE"})
    assert c == "ESTÁGIO/BOLSA" and n is False
    c2, _, n2 = pb._natureza_prefeitura(con, "x", {"FOLHA DE ESTAGIARIOS"})
    assert c2 == "ESTÁGIO/BOLSA" and n2 is False


def test_prefeitura_comissionado_confirmado(con):
    c, det, n = pb._natureza_prefeitura(con, "fulano comissao", {"NORMAL"})
    assert c == "NOMEADO" and n is True and "ESPECIAL" in det


def test_prefeitura_carreira(con):
    c, det, n = pb._natureza_prefeitura(con, "beltrano carreira", {"NORMAL"})
    assert c == "EFETIVO" and n is False and "GUARDA MUNICIPAL" in det


def test_prefeitura_sem_cargo_e_nao_informado(con):
    """Sem cargo conhecido: NUNCA presume comissionamento — declara que a fonte não informa."""
    c, det, n = pb._natureza_prefeitura(con, "sicrano desconhecido", {"NORMAL"})
    assert c == "NÃO INFORMADO" and n is None
    assert "não publica" in det


def test_classificar_consolidado_dois_poderes(con):
    """Câmara nomeado + Prefeitura efetivo → eh_nomeado=True (qualquer comissão confirma)."""
    info = {"poder": "Câmara + Prefeitura", "vinculo": "Livre Nomeação e Exoneração",
            "folha_desde": "202401", "tipos_folha": {"NORMAL"}}
    nat = pb._classificar_vinculo(con, "beltrano carreira", info)
    assert nat["eh_nomeado"] is True
    assert "Câmara: NOMEADO" in nat["natureza"] and "Pref.: EFETIVO" in nat["natureza"]


def test_classificar_indeterminado_nao_vira_nao(con):
    """Efetivo na Câmara + natureza não informada na Prefeitura → None (não vira 'não')."""
    info = {"poder": "Câmara + Prefeitura", "vinculo": "PROCURADOR DA CMRJ",
            "folha_desde": "202401", "tipos_folha": {"NORMAL"}}
    nat = pb._classificar_vinculo(con, "sicrano desconhecido", info)
    assert nat["eh_nomeado"] is None
