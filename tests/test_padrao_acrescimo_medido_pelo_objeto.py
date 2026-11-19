# -*- coding: utf-8 -*-
"""acrescimo_medido_pelo_objeto — Seleta (SEI-210108/000153/2023): TA 02/10/2025 de 14,59%; pago mensal ~R$ 0,85 mi → ~R$ 2,27 mi."""
from compliance_agent.padroes.acrescimo_medido_pelo_objeto import avaliar, crescimento

ANTES = {"2025-04": 821262.37, "2025-05": 851156.17, "2025-06": 789635.78, "2025-07": 802274.48, "2025-08": 799386.38}


def test_positivo_seleta():
    mensal = {**ANTES, "2025-12": 2300000.0, "2026-01": 2272659.54, "2026-02": 2250000.0, "2026-03": 2400000.0}
    cr = crescimento(mensal, "2025-10-02")
    assert cr and cr["g"] > 1.5 and avaliar(14.59, cr["g"], 0.25) == "forte"


def test_negativo_crescimento_compativel_com_o_declarado():
    mensal = {**ANTES, "2025-12": 1000000.0, "2026-01": 1010000.0, "2026-02": 990000.0}
    cr = crescimento(mensal, "2025-10-02")
    assert avaliar(25.0, cr["g"], 0.25) is None


def test_serie_curta_e_indisponivel():
    assert crescimento({"2025-09": 1.0, "2025-12": 2.0}, "2025-10-02") is None
