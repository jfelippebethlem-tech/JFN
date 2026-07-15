# -*- coding: utf-8 -*-
"""Testes do classificador de esfera (federal / estadual-RJ / municipal-Rio)."""
import pytest

from compliance_agent.pcrj.esfera import classificar_esfera


@pytest.mark.parametrize("nome,cnpj,esperado", [
    ("ESTADO DO RIO DE JANEIRO", "42498600000171", "estadual-rj"),
    ("MUNICIPIO DE RIO DE JANEIRO", "42498733000148", "municipal-rio"),
    ("COMANDO DA MARINHA", "00394502000144", "federal"),
    ("MINISTERIO DA SAUDE", "00394544000185", "federal"),
    ("FUNDACAO OSWALDO CRUZ", "33781055000135", "federal"),
    ("UNIVERSIDADE FEDERAL DO RIO DE JANEIRO", "33663683000116", "federal"),
    # armadilha: MP do Estado contém "MINISTÉRIO" mas é estadual, não federal
    ("MINISTERIO PUBLICO DO ESTADO DO RIO DE JANEIRO", "28305936000140", "estadual-rj"),
    ("SECRETARIA DE ESTADO DE SAUDE", "42498600000171", "estadual-rj"),
    ("PREFEITURA MUNICIPAL DO RIO DE JANEIRO - RJ", "42498733000148", "municipal-rio"),
    ("EMPRESA QUALQUER LTDA", "12345678000199", "indefinido"),
])
def test_classifica(nome, cnpj, esperado):
    assert classificar_esfera(nome, cnpj) == esperado


def test_raiz_uniao_federal_sem_nome():
    assert classificar_esfera("", "00394502002864") == "federal"


def test_indefinido_sem_sinal():
    assert classificar_esfera("", "") == "indefinido"


def test_cnpj_com_pontuacao():
    assert classificar_esfera("", "42.498.733/0001-48") == "municipal-rio"
