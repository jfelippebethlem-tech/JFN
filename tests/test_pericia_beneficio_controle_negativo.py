# -*- coding: utf-8 -*-
"""A faixa MÉDIA desta perícia é RUÍDO, e a própria lista prova.

O cruzamento sócio × benefício assistencial casa por NOME e, quando o fragmento de CPF do QSA bate
com o do arquivo do benefício, marca `ALTA` — aí é praticamente a mesma pessoa. Sem o fragmento,
marca `MÉDIA`.

Medido em 2026-08-12, restringindo aos fornecedores COM contrato da Prefeitura do Rio: 125
casamentos com Bolsa Família/Auxílio Brasil, dos quais **apenas 3 são ALTA**. E entre os 122
`MÉDIA` aparecem **INFRAERO, Banco Bradesco, Concremat, Elevadores Atlas Schindler, Microsens
S.A.** — diretor de banco e de estatal não recebe Bolsa Família. Isso não é hipótese: é controle
negativo, e ele condena a faixa.

O relatório já dizia que MÉDIA é "CPF não confirmado". O que faltava era o NÚMERO: sem medir quanto
da faixa é implausível, "não confirmado" soa como "provavelmente sim". Com o número, quem lê sabe
que a faixa não é fila de trabalho.

A régua do implausível é deliberadamente CONSERVADORA — sociedade anônima, banco, estatal e
multinacional listada. Não pretende achar todo falso positivo: pretende provar que existem tantos
que a faixa não se sustenta.
"""
from __future__ import annotations

from compliance_agent.pcrj.pericia_socios_beneficio import empresa_implausivel


def test_estatal_e_banco_sao_implausiveis():
    assert empresa_implausivel("EMPRESA BRASILEIRA DE INFRAESTRUTURA AEROPORTUARIA") is True
    assert empresa_implausivel("BANCO BRADESCO S/A") is True
    assert empresa_implausivel("MICROSENS S.A.") is True


def test_multinacional_listada_e_implausivel():
    assert empresa_implausivel("ELEVADORES ATLAS SCHINDLER LTDA.") is True
    assert empresa_implausivel("JANSSEN CILAG FARMACEUTICA LTDA") is True


def test_empresa_pequena_NAO_e_implausivel():
    """A régua não pode engolir o sinal: MEI e EPP são exatamente onde o achado real mora."""
    assert empresa_implausivel("KIFERRO FERRAGENS EPP LTDA") is False
    assert empresa_implausivel("52.582.377 ISABEL ERIDNEA CERVO RURR DE OLIVEIRA") is False
    assert empresa_implausivel("REVITALIZARY BEM ESTAR E QUALIDADE DE VIDA LTDA") is False


def test_ong_nao_e_implausivel_por_ser_ong():
    """Entidade sem fins lucrativos é justamente um dos alvos do pedido — não pode ser filtrada
    como 'grande demais'."""
    assert empresa_implausivel("ASSOCIACAO INSTITUTO FLORESTA") is False
    assert empresa_implausivel("CENTRAL UNICA DAS FAVELAS DO RIO DE JANEIRO") is False


def test_nome_vazio_nao_quebra():
    assert empresa_implausivel(None) is False
    assert empresa_implausivel("") is False
