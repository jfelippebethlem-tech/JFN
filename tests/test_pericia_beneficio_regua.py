# -*- coding: utf-8 -*-
"""Casar por NOME quando a fonte não traz o fragmento de CPF é inverificável por construção.

Medido em 2026-08-12 na base de benefício do Rio (2.206.234 linhas):

    Bolsa Família         986.173 linhas · fragmento de CPF em 77,3%
    Auxílio Brasil        414.130 linhas ·                      84,7%
    Auxílio Emergencial   466.432 linhas ·                       0,0%
    BPC                   329.015 linhas ·                       0,0%
    Gás do Povo            10.484 linhas ·                       0,0%

BPC, Auxílio Emergencial e Gás do Povo NUNCA trazem o fragmento. Um casamento nesses programas é
por nome e ponto — e nome brasileiro comum casa com muita gente. Era isso que enchia a faixa
`MÉDIA` com diretores de Bradesco, INFRAERO e Atlas Schindler.

A régua antiga tinha ainda um defeito pior: quando o fragmento do sócio EXISTIA e DISCORDAVA do
fragmento do beneficiário, o caso continuava saindo como `MÉDIA` — quando o fragmento discordante
é prova de que são pessoas DIFERENTES. São 25 casos, e todos saíam num relatório como se fossem
indício.

Três estados, portanto, e cada um significa uma coisa:

    ALTA            fragmentos batem — praticamente a mesma pessoa
    SEM_FRAGMENTO   a fonte não expõe fragmento nesse registro — inverificável, NÃO é indício
    (descartado)    fragmentos DISCORDAM — homônimo provado, sai da lista
"""
from __future__ import annotations

from compliance_agent.pcrj.pericia_socios_beneficio import classificar_casamento


def test_fragmentos_batem_e_ALTA():
    assert classificar_casamento("123456", {"123456"})[0] == "ALTA"


def test_fragmentos_discordam_e_DESCARTADO():
    """O fragmento discordante é prova de pessoa diferente — não pode virar indício."""
    assert classificar_casamento("123456", {"999999"})[0] == "DESCARTADO"


def test_fonte_sem_fragmento_e_SEM_FRAGMENTO():
    """BPC e Auxílio Emergencial nunca trazem fragmento: casamento por nome, inverificável."""
    assert classificar_casamento("123456", {"?"})[0] == "SEM_FRAGMENTO"


def test_socio_sem_mascara_e_SEM_FRAGMENTO():
    """Sem a máscara do QSA não há o que comparar — mesma categoria de honestidade."""
    assert classificar_casamento("", {"123456"})[0] == "SEM_FRAGMENTO"


def test_varios_homonimos_sem_casar_e_DESCARTADO():
    """Vários beneficiários com o mesmo nome e nenhum casa o fragmento: já era descartado antes,
    e continua."""
    assert classificar_casamento("123456", {"111111", "222222"})[0] == "DESCARTADO"


def test_um_dos_varios_casa_e_ALTA():
    assert classificar_casamento("222222", {"111111", "222222"})[0] == "ALTA"


def test_devolve_o_fragmento_escolhido():
    """Quem chama precisa do fragmento para achar o registro do beneficiário."""
    assert classificar_casamento("123456", {"123456"})[1] == "123456"
    assert classificar_casamento("", {"?"})[1] == "?"
