# -*- coding: utf-8 -*-
"""kit_acima_do_estimado_etp — Brasil Comércio (SEI-030001/087803/2025): ETP R$ 278,41 × contrato R$ 309,80 (ID 184730)."""
from compliance_agent.padroes._carona_comum import Doc
from compliance_agent.padroes.kit_acima_do_estimado_etp import avaliar, precos_por_id

ETP = Doc("arquivo", "15", "Estudo Técnico Preliminar (110287342)",
          "1\nKIT ESCOLAR ALUNO - COMPOSICAO:\n04 CAMISETAS ESCOLARES UNISSEX,\nFORNECIMENTO:\nUNIDADE - ID: 184730 - "
          "Código do\nItem: 8410.022.0007\nUN\n1557480\nR$ 278,41\nR$ 433.618.006,80\n2\nPAR DE TENIS ID: 173149 - "
          "Código do Item: 8430.001.0001\nPAR\n1557480\nR$ 92,85\nR$ 144.611.018,00")
CONTRATO = Doc("arquivo", "18", "Contrato nº20.2025 (110287345)",
               "4\nAQUISIÇÃO DE\nCONJUNTO COMPLETOS\nDE UNIFORME ESCOLAR\n(ID - 184730)\nDIESP\nNOROESTE\n74.124\n"
               "R$ 309,80\nR$\n22.963.615,20\n16\nPAR DE TÊNIS ESCOLAR\n(ID - 173149)\nDIESP\n48.107\nR$ 76,68\nR$\n3.688.844,76")


def test_trinca_le_codigo_de_item_sem_confundir():
    p = precos_por_id(ETP)
    assert p["184730"][0] == 278.41 and p["173149"][0] == 92.85


def test_positivo_kit_acima_do_etp():
    r = avaliar([ETP, CONTRATO])
    assert len(r) == 1 and r[0]["id_siga"] == "184730" and r[0]["grau"] == "forte" and r[0]["excesso_pct"] == 11.27


def test_negativo_tenis_abaixo_e_estimativa_maior_no_tr():
    tr = Doc("arquivo", "16", "Termo de Referência", "ID: 184730 UN 100 R$ 320,00 R$ 32.000,00")
    assert avaliar([ETP, tr, CONTRATO]) == []


def test_negativo_numero_sem_trinca_nao_vira_preco():
    c = Doc("arquivo", "18", "Contrato", "(ID - 184730) página 12 de 40 CNPJ 11.210.951/0001-01 R$ 309,80")
    assert avaliar([ETP, c]) == []
