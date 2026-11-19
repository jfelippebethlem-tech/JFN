# -*- coding: utf-8 -*-
"""retificacao_altera_valor — Geo Ambiental (SEI-070002/005897/2024 doc 472) e Brasform (006481/2024)."""
from compliance_agent.padroes._aditivos_comum import divergencias_extenso, extenso_para_numero
from compliance_agent.padroes.retificacao_altera_valor import onde_le_leia_se

GEO = ("CLÁUSULA TERCEIRA: o contrato ora aditado foi reajustado através de Termo de Apostilamento, no valor de R$ "
       "1.815.002,86 (cinco milhões, setecentos e quinze mil, trezentos e setenta e nove reais e trinta e cinco "
       "centavos) referente ao 1° aniversário")


def test_extenso():
    assert extenso_para_numero("quarenta e cinco milhões, oitocentos e setenta e\ndois mil duzentos e dois reais e "
                               "sessenta e oito centavos") == 45872202.68
    assert extenso_para_numero("vinte e milhões, trezentos reais") is None            # malformado (Brasform 668)
    assert extenso_para_numero("dezesseis mil duzentos e trinta e nove mil reais") is None


def test_positivo_geo_numero_diferente_do_extenso():
    d = divergencias_extenso(GEO)
    assert d and d[0]["valor"] == 1815002.86 and d[0]["valor_extenso"] == 5715379.35


def test_negativo_numero_igual_ao_extenso_e_erro_de_uma_palavra():
    assert divergencias_extenso("R$ 45.872.202,68 (quarenta e cinco milhões, oitocentos e setenta e dois mil "
                                "duzentos e dois reais e sessenta e oito centavos)") == []
    assert divergencias_extenso("R$ 14.499,00 (quatorze mil, quatrocentos e quarenta e nove reais)") == []


def test_positivo_onde_se_le_leia_se_com_valor():
    t = ("CLÁUSULA PRIMEIRA: Onde se lê: totalizando o contrato o valor de R$ 17.661.325,44. Leia-se: totalizando o "
         "contrato o valor de R$ 20.617.970,44.")
    r = onde_le_leia_se(t)
    assert r and r[0]["onde"] == [17661325.44] and r[0]["leia"] == [20617970.44] and r[0]["aumenta"]


def test_negativo_retificacao_sem_valor():
    assert onde_le_leia_se("CLÁUSULA PRIMEIRA: Onde se lê: Rua A. Leia-se: Rua B.") == []
