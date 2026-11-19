# -*- coding: utf-8 -*-
"""acrescimo_colado_no_teto — Brasform (SEI-070002/006481/2024) 19,96% + 4,35%; Hydra doc 264 (extrato do PRODERJ)."""
from compliance_agent.padroes._aditivos_comum import declaracoes_de_acrescimo
from compliance_agent.padroes.acrescimo_colado_no_teto import avaliar

TA42 = ("CLÁUSULA PRIMEIRA: alteração do Contrato nº 26/2022.\nPARÁGRAFO SEGUNDO: A alteração pretendida refere-se ao "
        "acréscimo do objeto contratual de itens\nacrescidos no valor de R$ 3.526.040,20 (três milhões, quinhentos e "
        "vinte e seis mil, quarenta reais e vinte\nTermo Aditivo 79635048         SEI SEI-070002/008302/2022 / pg. 1\n\n"
        "centavos) corresponde ao percentual de 19,96% e a supressão de itens no valor de 569.395,20\n"
        "Documento assinado eletronicamente por Fulano, Diretor, em 25/07/2024, às 10:00")
TA43 = ("CLÁUSULA PRIMEIRA: Termo Aditivo ao Contrato nº 26/2022. resultará em acréscimo do objeto contratual, no "
        "percentual de 4,35% do valor inicial atualizado. Documento assinado eletronicamente por X, em 15/07/2025, às 9:00")


def test_rodape_no_meio_da_frase_nao_corta_a_leitura():
    d = declaracoes_de_acrescimo(TA42)
    assert d and d[0]["pct"] == 19.96


def test_positivo_brasform_soma_encostada():
    decl = declaracoes_de_acrescimo(TA42) + declaracoes_de_acrescimo(TA43)
    v = avaliar(decl)
    assert v["grau"] == "medio" and abs(v["soma_pct"] - 24.31) < 0.001


def test_positivo_acima_do_teto_pelo_bruto():
    v = avaliar([{"pct": 24.87, "pct_supressao": 2.5, "trecho": "acréscimo"}, {"pct": 3.0, "trecho": "acréscimo"}])
    assert v["grau"] == "forte" and "BRUTO" in v["motivo"]


def test_negativo_25_exatos_e_permitido_e_reforma_tem_50():
    assert avaliar([{"pct": 25.0, "trecho": "acréscimo"}])["grau"] == "medio"      # encostado, não estouro
    assert avaliar([{"pct": 30.0, "trecho": "acréscimo"}], "reforma de edifício escolar") is None


def test_negativo_soma_baixa_e_reajuste():
    assert avaliar([{"pct": 10.0, "trecho": "acréscimo"}, {"pct": 13.5, "trecho": "acréscimo"}]) is None
    assert avaliar([{"pct": 24.5, "trecho": "acréscimo decorrente do reajuste pelo IPCA"}]) is None


def test_negativo_extrato_de_outro_contrato_na_pagina_do_doerj():
    t = ("Termo Aditivo ao Contrato nº 11/2024 acréscimo no percentual de 24,87%.\nINSTITUTO ESTADUAL DO AMBIENTE\n"
         "EXTRATO DE TERMO ADITIVO\nINSTRUMENTO : Primeiro Termo Aditivo ao Contrato nº 20/2024\nOBJETO: prorrogação."
         " PARÁGRAFO PRIMEIRO: A\nalteração ora firmada resultará em acréscimo do objeto contratual, no\npercentual de 25%")
    assert [x["pct"] for x in declaracoes_de_acrescimo(t)] == [24.87]
