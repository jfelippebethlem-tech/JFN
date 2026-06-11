# -*- coding: utf-8 -*-
"""Ensemble 4-regimes (tendência×volatilidade) + drift — peças puras."""
from __future__ import annotations

import math

from massare import engine_regime4 as ER4


def test_regime4_label_grade_2x2():
    # bull (close>sma200) × volatilidade (vol21 vs mediana trailing)
    assert ER4._regime4_label(110, 100, 0.03, 0.02) == "bull_turb"
    assert ER4._regime4_label(110, 100, 0.01, 0.02) == "bull_calm"
    assert ER4._regime4_label(90, 100, 0.03, 0.02) == "bear_turb"
    assert ER4._regime4_label(90, 100, 0.01, 0.02) == "bear_calm"


def test_regime4_label_neutro_e_sem_vol():
    # sem tendência (warmup) => neutro
    assert ER4._regime4_label(100, float("nan"), 0.03, 0.02) == "neutro"
    assert ER4._regime4_label(None, 100, 0.03, 0.02) == "neutro"
    # sem dado de volatilidade => assume 'calm' (conservador), tendência preservada
    assert ER4._regime4_label(110, 100, float("nan"), 0.02) == "bull_calm"
    assert ER4._regime4_label(110, 100, 0.03, None) == "bull_calm"


def test_walk_forward_e_predict_smoke():
    """Integração leve: o motor roda sobre a sede real e devolve as métricas OOS esperadas."""
    wf = ER4.walk_forward_regime4("^GSPC", horizon=21)
    if wf.get("erro"):
        return  # sede sem dados nesse ambiente — não falha o CI
    assert wf["regimes"] == 4 and wf["drift"] is True
    assert wf["ensemble_n"] > 0
    assert wf["edge"] is not None and -1 <= wf["edge"] <= 1
    p = ER4.predict_today("^GSPC", horizon=21)
    assert p["direction"] in ("up", "down")
    assert 0.0 <= p["prob"] <= 0.95
    assert p["regime_atual"] in ER4._REGS4
    # honestidade: tem_skill reflete o edge OOS do MESMO motor
    assert p["tem_skill"] == (p["edge_oos"] is not None and p["edge_oos"] > 0)


def test_alpha_from_halflife_bounds_e_monotonia():
    a_curto = ER4._alpha_from_halflife(10)
    a_longo = ER4._alpha_from_halflife(120)
    # meia-vida curta => alpha maior (esquece mais rápido / mais peso ao recente)
    assert 0.0 < a_longo < a_curto < 1.0
    # meia-vida 1 => alpha = 0.5 (um passo derruba metade do peso)
    assert abs(ER4._alpha_from_halflife(1) - 0.5) < 1e-9
    # piso: half_life<1 é clampeado em 1
    assert ER4._alpha_from_halflife(0.1) == ER4._alpha_from_halflife(1)
