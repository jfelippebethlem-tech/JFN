# -*- coding: utf-8 -*-
"""A fila do COLETOR — recurso mais escasso da casa (sessão única do SEI, WAF, um browser).

Ordenar só por valor mandava metade do esforço para folha de inativos. Medido na fonte SIAFE em
2026-08-04: 66 dos 200 maiores processos por valor pago eram folha/previdência/encargo,
R$ 5,73 bi contra R$ 5,42 bi de contratação.
"""
import pytest

from tools.sei_fila_por_dinheiro import e_folha_ou_encargo


@pytest.mark.parametrize("credor", [
    "RIOPREV/INATIVOS",
    "PLANO DE BENEFICIOS RJPREV CD",
    "TJ - Folha de Pagamento de Inativos",
    "FUNDO DE EQUALIZACAO FEDERATIVA - FEF",
    "FOLHA DE PAGAMENTOS",
])
def test_folha_e_encargo_saem_da_frente_da_fila(credor):
    assert e_folha_ou_encargo(credor) is True


@pytest.mark.parametrize("credor", [
    "CONSTRUTORA METROPOLITANA S.A",
    "I.D.E.A.S - INSTITUTO DESENVOLVIMENTO",
    "INSTITUTO D'OR DE GESTÃO DE SAÚDE",
    "LET'S RENT A CAR S/A",
])
def test_contratacao_continua_na_frente(credor):
    assert e_folha_ou_encargo(credor) is False


def test_raiz_da_uniao_e_tributo_nao_contratacao():
    """00394460 é a base da União (ministérios): pagamento à Fazenda é tributo/repasse. A casa já
    registra a raiz em `processo_360._cnpj_do_texto` — aqui ela vale pelo CNPJ, que é mais
    confiável que o nome (grafia varia, raiz não)."""
    assert e_folha_ou_encargo("MINISTÉRIO DA FAZENDA", "00394460010880") is True
    assert e_folha_ou_encargo("CONSTRUTORA X", "33049503000100") is False


def test_sem_credor_nao_afirma_que_e_folha():
    """Ausência de nome não é prova de nada — INDISPONÍVEL ≠ folha."""
    assert e_folha_ou_encargo(None) is False
    assert e_folha_ou_encargo("", "") is False
