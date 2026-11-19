# -*- coding: utf-8 -*-
"""aditivo_absorve_outro_lote — SEAP × Seleta (SEI-210108/000153/2023, doc 873) e Cassarotti (000169/2023, doc 1985)."""
from compliance_agent.padroes.aditivo_absorve_outro_lote import analisar_texto, grau

SELETA = ("CLÁUSULA PRIMEIRA (Do Objeto): Constitui objeto do presente instrumento a alteração\nquantitativa do Contrato nº "
          "23/2023, relativo à prestação de serviços contínuos de nutrição, com\nfundamento no inciso I, alínea b do art. 65, "
          "c/c art. 58, inciso I, da Lei nº 8.666/93.\n \nPARÁGRAFO PRIMEIRO: Ressalta-se que o presente Termo Aditivo ao "
          "Contrato nº 23/2023\ndecorre da absorção parcial do Contrato nº 14/2020, referente ao lote 12 (Penitenciária\n"
          "Industrial Esmeraldino Bandeira - EB) de modo a permitir que as\nempresas atualmente contratadas pela SEAP possam "
          "assumir a prestação dos serviços nas\nunidades prisionais abrangidas.\nPARÁGRAFO SEGUNDO: A alteração ora firmada "
          "resultará em acréscimo do objeto contratual, no\npercentual de 14,59% no quantitativo do valor inicial atualizado")


def test_positivo_seleta_absorve_lote_12():
    oc = analisar_texto(SELETA, "Contrato 23/2023 - : 5º Termo Aditivo (118932960)")
    assert oc and oc[0]["contratos_absorvidos"] == ["14/2020"] and oc[0]["lotes"] == ["12"]
    assert oc[0]["pct_declarado"] == 14.59 and grau(oc[0]) == "forte"


def test_positivo_compilacao_com_varios_contratos_absorvidos():
    t = ("CLÁUSULA PRIMEIRA: alteração quantitativa. PARÁGRAFO PRIMEIRO: Ressalta-se que o presente Termo Aditivo ao "
         "Contrato nº 25/2023 decorre da absorção parcial dos Contratos nº 07/2020, 14/2019 e 07/2019, referentes aos "
         "lotes 19, 09 e 13. acréscimo do objeto contratual, no percentual de 25%")
    oc = analisar_texto(t, "Contrato N° 18/2023 - ATÉ O 3° TERMO ADITIVO")
    assert set(oc[0]["contratos_absorvidos"]) == {"7/2020", "14/2019", "7/2019"} and grau(oc[0]) == "forte"


def test_negativo_absorcao_do_proprio_contrato():
    t = ("CLÁUSULA PRIMEIRA: alteração quantitativa do Contrato nº 23/2023, decorre da absorção parcial do Contrato nº "
         "23/2023, acréscimo no percentual de 10%")
    assert analisar_texto(t, "Contrato 23/2023 - 2º Termo Aditivo") == []


def test_negativo_acrescimo_sem_absorcao():
    t = "CLÁUSULA PRIMEIRA: alteração quantitativa do Contrato nº 23/2023, acréscimo do objeto no percentual de 25%."
    assert analisar_texto(t, "Termo Aditivo") == []


def test_negativo_absorcao_em_extrato_do_doerj():
    t = ("Termo Aditivo ao Contrato nº 23/2023 ... assinado.\nDIÁRIO OFICIAL DO ESTADO DO RIO DE JANEIRO\nEXTRATO DE "
         "TERMO ADITIVO\nINSTRUMENTO: 1º TA ao Contrato nº 9/2024. OBJETO: absorção parcial do Contrato nº 3/2021, "
         "referente ao lote 4")
    assert analisar_texto(t, "Termo Aditivo") == []
