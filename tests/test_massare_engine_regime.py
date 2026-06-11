# -*- coding: utf-8 -*-
"""Ensemble regime-condicional — rótulo de regime (puro)."""
from __future__ import annotations

import math

from massare import engine_regime as ER


def test_regime_label_bull_bear_neutro():
    assert ER._regime_label({"close": 110, "sma200": 100}) == "bull"
    assert ER._regime_label({"close": 90, "sma200": 100}) == "bear"
    assert ER._regime_label({"close": 100, "sma200": float("nan")}) == "neutro"
    assert ER._regime_label({"close": 100, "sma200": None}) == "neutro"
    assert ER._regime_label({"close": None, "sma200": 100}) == "neutro"


def test_nan_e_neutro():
    assert ER._regime_label({"close": 100, "sma200": math.nan}) == "neutro"
