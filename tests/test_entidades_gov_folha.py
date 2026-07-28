# -*- coding: utf-8 -*-
"""Credores que recebem OB e não são contratação — as famílias que faltavam.

Medido em 2026-07-28 ao montar a fila de CAPTURA prioritária (processos com pagamento e sem
texto). Os TRÊS maiores por valor não eram contratação nenhuma:

    R$ 1.418.765.491,04   FUNDO DE EQUALIZACAO FEDERATIVA - FEF   (transferência constitucional)
    R$   571.694.263,65   RIOPREV/INATIVOS                        (previdência)
    R$   276.483.779,27   FOLHA DE PAGAMENTOS                     (pessoal)

Nenhum deles passa por licitação, e nenhum tem fornecedor a fiscalizar. Deixá-los no topo de
uma fila de fiscalização de COMPRAS gasta a primeira hora do dia do analista com o que não é
o objeto — e infla qualquer número de manchete que some "pagamento sem processo capturado".
"""
from __future__ import annotations

import pytest

from compliance_agent.entidades_gov import eh_nao_fornecedor


@pytest.mark.parametrize("nome", [
    "FUNDO DE EQUALIZACAO FEDERATIVA - FEF",
    "Fundo de Participação dos Municípios",
    "RIOPREV/INATIVOS",
    "RIOPREV - PENSIONISTAS",
    "FOLHA DE PAGAMENTOS",
    "FOLHA DE PESSOAL ATIVO",
    "PRECATORIOS - SENTENCAS JUDICIAIS",
    "RESTITUICAO DE RECEITA",
])
def test_nao_sao_contratacao(nome):
    assert eh_nao_fornecedor(nome) is True, f"{nome!r} não é fornecedor de compra"


@pytest.mark.parametrize("nome", [
    "ACME SERVICOS LTDA",
    "AMPLA ENERGIA E SERVICOS S/A",
    "CONSTRUTORA FOLHA VERDE LTDA",      # "folha" no nome de empresa não é folha de pagamento
    "FUNDACAO GETULIO VARGAS",
    "INSTITUTO DE PESQUISA APLICADA LTDA",
])
def test_fornecedor_de_verdade_nao_e_excluido(nome):
    """O risco do filtro largo é o oposto: excluir empresa real e cegar a fiscalização."""
    assert eh_nao_fornecedor(nome) is False, f"{nome!r} é fornecedor e foi excluído"


def test_as_familias_antigas_continuam_valendo():
    for nome in ("Fundo Municipal De Saude De Itaborai", "MUNICIPIO DE NITEROI",
                 "INSS", "Secretaria de Estado de Educacao"):
        assert eh_nao_fornecedor(nome) is True


# ── abreviações: o dado real não escreve por extenso ───────────────────────────────────────
# Medido em 2026-07-28 na fila viva de fracionamento: 617 credores, 20 escapando do filtro por
# abreviação. "Fundo Munic.de Saude/sus Munic.de Resende" é entidade pública e estava sendo
# ofertada ao analista como candidato a fracionamento de COMPRA.

@pytest.mark.parametrize("nome", [
    "Fundo Munic.de Saude/sus Munic.de Resende",
    "Fundo Mun.de Saude De Eng.paulo De Frontin",
    "Fundo Munic.de Saude De Cachoeiras De Macacu",
    "Pref Munic De Campos De Goytacazes",
    "DIRETORIA REGIONAL ADMINISTRATIVA METROPOLITANA VII",
])
def test_abreviacoes_de_ente_publico_sao_filtradas(nome):
    assert eh_nao_fornecedor(nome) is True


@pytest.mark.parametrize("nome", [
    "Aae Ciep Brizolao 218 Ministro Hermes Lima",
    "ASSOCIAÇÃO DE APOIO A ESCOLA CIEP BRIZOLÃO 393 PREFEITO CARLOS EMI",
    "Aae Do Inst De Ed Prof Ismael Coutinho",
])
def test_associacao_de_apoio_a_escola_recebe_repasse_nao_contrata(nome):
    """AAE recebe transferência para custeio da unidade escolar — não é fornecedor de compra,
    e numa fila de fracionamento de COMPRA ela é ruído."""
    assert eh_nao_fornecedor(nome) is True


@pytest.mark.parametrize("nome", [
    "FUNDACAO GETULIO VARGAS",
    "REPÚBLICA ADMINISTRAÇÃO E SERVIÇOS LTDA",
    "ASSOCIACAO BRASILEIRA DE ENSINO LTDA",
    "INSTITUTO DE PESQUISA APLICADA LTDA",
])
def test_privado_com_nome_institucional_nao_e_filtrado(nome):
    """O risco simétrico: filtro largo demais cega a fiscalização sobre fornecedor real."""
    assert eh_nao_fornecedor(nome) is False
