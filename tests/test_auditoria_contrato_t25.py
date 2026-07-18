# -*- coding: utf-8 -*-
"""T25 — jogo de planilha (sobrepreço recuperado por aditivo). Determinístico, sem rede.

TCU (Acórdãos 1.755/2004, 2.988/2018-P): a caracterização INDEPENDE de dolo — basta o padrão
quantitativo de mergulho-na-licitação + recuperação-por-aditivo para o INDÍCIO.
"""
from compliance_agent.auditoria_contrato import _t25_jogo_planilha as t25


def test_jogo_planilha_classico_mergulho_e_recuperacao():
    h = t25({"objeto": "obra de macrodrenagem", "valor_estimado": 100_000_000,
             "valor_inicial": 68_000_000, "valor_global": 103_000_000, "n_aditivos": 3})
    assert h["status"] == "INDICIO" and h["nivel"] == "alto"
    assert "mergulho" in h["evidencia"].lower() and "independe de dolo" in h["evidencia"].lower()


def test_jogo_planilha_acrescimo_sem_estimativa_ainda_indicia():
    # sem estimativa, um acréscimo grande por aditivo em obra ainda é indício (nível médio)
    h = t25({"objeto": "construção de escola", "valor_inicial": 10_000_000,
             "valor_global": 14_000_000, "n_aditivos": 2})
    assert h["status"] == "INDICIO"


def test_servico_continuo_reajuste_nao_e_jogo_de_planilha():
    # limpeza com reajuste anual NÃO é obra → AFASTADO (evita falso-positivo em serviço contínuo)
    h = t25({"objeto": "limpeza e conservação predial", "valor_inicial": 5_000_000,
             "valor_global": 6_500_000, "n_aditivos": 2})
    assert h["status"] == "AFASTADO"


def test_obra_sem_aditivo_afastado():
    h = t25({"objeto": "pavimentação", "valor_inicial": 8_000_000,
             "valor_global": 8_000_000, "n_aditivos": 0})
    assert h["status"] == "AFASTADO"


def test_obra_acrescimo_dentro_do_teto_afastado():
    # +20% (abaixo do teto de 25% do art. 125) não dispara
    h = t25({"objeto": "obra viária", "valor_inicial": 10_000_000,
             "valor_global": 12_000_000, "n_aditivos": 1})
    assert h["status"] == "AFASTADO"


def test_sem_valores_indisponivel_nao_fabrica_achado():
    h = t25({"objeto": "obra"})
    assert h["status"] == "INDISPONIVEL" and "falta" in h["evidencia"].lower()
