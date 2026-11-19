# -*- coding: utf-8 -*-
"""faixa_de_volume_estendida — Poupa Tempo (SEI-150001/000224/2025, docs 9 e 12)."""
from compliance_agent.padroes.faixa_de_volume_estendida import _RE_INTERNET, faixas_novas, grau_extensao, maximo_faixa

CONTRATO = ("FAIXAS\nDE\nATÉ\nFATOR DE ATENDIMENTO\nFAIXA 1\n0\n6.500\n6.000\nFAIXA 2\n6.501\n7.500\n7.000\n"
            "FAIXA 4\n8.501\n9.500\n9.000\nFAIXA 5\n9.501\n10.500\n10.000\n")
TA2 = ("CLÁUSULA PRIMEIRA: PARÁGRAFO SEGUNDO: O contrato ora aditado passa a permitir, havendo saldo contratual, o\n"
       "quantitativo de atendimentos na faixa de até 20.000 atendimentos/dia, conforme tabela abaixo. resultará em "
       "acréscimo do objeto contratual, no percentual de 25%")


def test_positivo_poupa_tempo():
    assert maximo_faixa(CONTRATO) == 10500
    n = faixas_novas(TA2)
    assert n[0]["novo_max"] == 20000 and n[0]["pct"] == 25.0
    assert grau_extensao(20000 / 10500 - 1, 25.0, 0.25) == "forte"


def test_negativo_faixa_mantida():
    assert grau_extensao(10500 / 10500 - 1, 25.0, 0.25) is None
    assert grau_extensao(0.30, 25.0, 0.25) is None


def test_internet_como_atendimento():
    assert _RE_INTERNET.search("Acesso Gratuito à Internet (POUPA TEMPO VIRTUAL) – 70.545 atendimentos")
    assert not _RE_INTERNET.search("Emissão de carteira de identidade – 70.545 atendimentos")
