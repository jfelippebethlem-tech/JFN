# -*- coding: utf-8 -*-
"""Emergência que se repete 245 vezes no ano deixa de ser emergência.

Achado ao avaliar o sweep de fracionamento da VM-2 (2026-07-28). O grupo de topo era a
SEDSODH/2024, e a composição contava outra história: **LOCALMED com 147 contratações
"EMERGENCIAIS" somando R$ 8,5 milhões** — matéria do art. 75, VIII, não do fracionamento por
valor. Varrendo a base inteira:

    contratações com objeto EMERGENCIAL .......... 1.638 · R$ 1.963.745.047,92
      FSERJ 2023 ................................... 245 · R$   392.350.345,76
      SEDSODH 2023 ................................. 471 · R$   121.557.667,80
      UERJ Hospital Universitário 2024 ............. 203 · R$   120.101.832,55

O art. 75, VIII exige **imprevisibilidade** e urgência que impeça o rito normal. Uma unidade
que contrata em emergência centenas de vezes por ano não enfrenta o imprevisível: ela deixou
de planejar — e a jurisprudência do TCU trata emergência decorrente de desídia administrativa
como irregular ("emergência fabricada").

O QUE ESTA RÉGUA NÃO FAZ: não chama emergência de irregular. Emergência é instrumento legal e
necessário. O indício é a RECORRÊNCIA — e ela é medida, não presumida.
"""
from compliance_agent.fracionamento_emergencia import agrupar_emergencias

L = [  # (unidade, exercicio, fornecedor, valor, objeto)
    ("FSERJ", 2023, "ALFA", 100_000.0, "CONTRATAÇÃO EMERGENCIAL DE INSUMOS"),
    ("FSERJ", 2023, "ALFA", 200_000.0, "CONTRATAÇÃO EMERGENCIAL DE INSUMOS"),
    ("FSERJ", 2023, "ALFA", 300_000.0, "CONTRATAÇÃO EMERGENCIAL DE INSUMOS"),
    ("FSERJ", 2023, "BETA", 50_000.0, "AQUISIÇÃO NORMAL"),
    ("SUDERJ", 2024, "GAMA", 90_000.0, "CONTRATAÇÃO EMERGENCIAL PONTUAL"),
]


def test_so_conta_o_que_e_emergencial():
    g = agrupar_emergencias(L, minimo=1)
    fserj = [x for x in g if x["unidade"] == "FSERJ"][0]
    assert fserj["n"] == 3, "a aquisição normal não entra no grupo de emergência"
    assert fserj["total"] == 600_000.0


def test_emergencia_pontual_nao_vira_achado():
    """Uma emergência isolada é o uso LEGÍTIMO do art. 75, VIII."""
    g = agrupar_emergencias(L, minimo=3)
    assert not [x for x in g if x["unidade"] == "SUDERJ"]


def test_recorrencia_no_mesmo_fornecedor_e_sinal_mais_forte():
    """Repetir emergência sempre com o MESMO fornecedor é fuga à licitação, não urgência."""
    g = agrupar_emergencias(L, minimo=1)
    fserj = [x for x in g if x["unidade"] == "FSERJ"][0]
    assert fserj["fornecedor_dominante"] == "ALFA"
    assert fserj["concentracao_dominante"] == 1.0


def test_grupos_saem_ordenados_por_valor():
    """Fiscalizar em ordem alfabética desperdiça a primeira hora do dia."""
    g = agrupar_emergencias(L + [("X", 2024, "Z", 9_000_000.0, "EMERGENCIAL")], minimo=1)
    assert g[0]["unidade"] == "X"


def test_lista_vazia_nao_quebra():
    assert agrupar_emergencias([], minimo=1) == []


def test_o_grupo_declara_o_que_NAO_afirma():
    """Sem a ressalva, a saída vira acusação de irregularidade — que ela não é."""
    g = agrupar_emergencias(L, minimo=1)
    assert "ressalva" in g[0] and "indício" in g[0]["ressalva"].lower()
