# -*- coding: utf-8 -*-
"""Testes do extrator de preços unitários + sobrepreço interno (determinístico, sem rede)."""
from __future__ import annotations

from compliance_agent import precos_extract as P


EDITAL_TAB = """
ANEXO I - PLANILHA DE ITENS
1   Caneta esferográfica azul    UN   1000   R$ 1,50    R$ 1.500,00
2   Resma papel A4 500 folhas    RESMA   200   R$ 25,00   R$ 5.000,00
3   Notebook i5 8GB              UN   10     R$ 3.200,00  R$ 32.000,00
"""

EDITAL_EXPL = "Item único: aquisição de cadeira giratória. Quantidade: 50. Valor Unitário: R$ 450,00."


def test_extrai_tabela():
    itens = P.extrair_itens(EDITAL_TAB)
    descrs = {i["descricao"] for i in itens}
    assert any("CANETA" in d for d in descrs)
    assert any("NOTEBOOK" in d for d in descrs)
    caneta = next(i for i in itens if "CANETA" in i["descricao"])
    assert caneta["preco_unitario"] == 1.50
    assert caneta["quantidade"] == 1000
    assert caneta["unidade"] == "UN"


def test_filtro_sanidade_total():
    # total inconsistente com qtd*unit → linha descartada (não polui)
    ruim = "1   Item bugado   UN   10   R$ 5,00   R$ 999.999,00"
    assert P.extrair_itens(ruim) == []


def test_extrai_explicito():
    itens = P.extrair_itens(EDITAL_EXPL)
    assert len(itens) == 1
    assert itens[0]["preco_unitario"] == 450.00
    assert itens[0]["quantidade"] == 50


def test_sobrepreco_interno_detecta_dispersao():
    regs = [
        {"descricao": "Caneta esferográfica azul", "preco_unitario": 1.50, "ref": "A", "orgao": "X"},
        {"descricao": "Caneta esferográfica azul", "preco_unitario": 1.80, "ref": "B", "orgao": "Y"},
        {"descricao": "Caneta esferografica azul", "preco_unitario": 4.50, "ref": "C", "orgao": "Z"},  # 3x!
    ]
    ach = P.sobrepreco_interno(regs, min_amostras=3)
    assert len(ach) == 1
    a = ach[0]
    assert a["razao_max_min"] == 3.0
    assert a["mais_caro"]["ref"] == "C" and a["mais_barato"]["ref"] == "A"
    assert a["sobrepreco_pct_vs_mediana"] > 0


def test_sobrepreco_amostra_insuficiente_nao_conclui():
    regs = [{"descricao": "X", "preco_unitario": 1.0, "ref": "A"},
            {"descricao": "X", "preco_unitario": 9.0, "ref": "B"}]
    assert P.sobrepreco_interno(regs, min_amostras=3) == []  # < 3 amostras → INDISPONÍVEL


def test_honesto_texto_vazio():
    assert P.extrair_itens("") == []
    assert P.extrair_itens("Edital sem nenhuma tabela de preços.") == []
