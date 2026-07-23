"""A página de ESCOLHA DE UNIDADE do SEI não é conteúdo de documento.

Achado em 2026-07-23, ao recapturar SEI-260007/004617/2024 (R$ 48,3 mi em OBs):
para documento de OUTRA unidade o SEI não serve o teor — devolve a tela de seleção
de unidade ("GOVERNO DO ESTADO DO RIO DE JANEIRO / Sistema Eletrônico de Informações
/ AGENERSA / AGERIO / AGETRANSP / CASERJ / CEASA / ..."). O drill capturava esses
904 caracteres como se fossem o documento.

Antes isso virava PDF em branco por acidente (lista de siglas = muitas linhas curtas
= `insert_textbox` estourava). Com o escritor corrigido, viraria algo pior: uma lista
de siglas gravada COMO SE FOSSE o teor do comprovante de pagamento. Falso conteúdo é
pior que conteúdo ausente — INDISPONÍVEL ≠ 0, e muito menos ≠ lixo.
"""
import pytest

from tools.sei_integra_completa import parece_pagina_de_unidade

_UNIDADE = (
    "GOVERNO DO ESTADO DO RIO DE JANEIRO\nSistema Eletrônico de Informações\n \n"
    "AGENERSA\nAGERIO\nAGETRANSP\nCASERJ\nCEASA\nCECIERJ\nCEDAE\nCEE\nCEHAB\n"
    "CENTRAL\nCEPERJ\nCGE\nCODERTE\nCODIN\nDDPE\nDEGASE\nDER\nDETRAN\nDETRO\n"
    "DRM\nEMATER\nEMOP\nERJ\nFAETEC\nFAPERJ\nFIA\nFIPERJ\nFLXIII\n"
)

_DOCUMENTO = (
    "GOVERNO DO ESTADO DO RIO DE JANEIRO\nSECRETARIA DE ESTADO DE SAÚDE\n\n"
    "COMPROVANTE DE PAGAMENTO\n\nOrdem Bancária 2024OB08797\n"
    "Favorecido: JRG DISTRIBUIDORA DE MEDICAMENTOS HOSPITALARES LTDA\n"
    "Valor: R$ 20.000,00\nData: 12/03/2024\n"
    "Empenho: 2024NE00123 — aquisição de medicamentos conforme ata de registro de preços.\n"
)


def test_reconhece_a_tela_de_selecao_de_unidade():
    assert parece_pagina_de_unidade(_UNIDADE) is True


def test_nao_confunde_documento_real_com_a_tela():
    assert parece_pagina_de_unidade(_DOCUMENTO) is False, \
        "comprovante legítimo não pode ser descartado como tela de unidade"


@pytest.mark.parametrize("texto", ["", "   ", "curto demais"])
def test_texto_irrelevante_nao_quebra(texto):
    assert parece_pagina_de_unidade(texto) is False
