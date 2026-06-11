# -*- coding: utf-8 -*-
"""FMP via chave grátis — núcleo PURO de fundamentos + degradação honesta sem chave."""
from __future__ import annotations

from massare import fmp


def test_montar_fundamentos_extrai_campos():
    km = [{"symbol": "AAPL", "marketCap": 3.5e12, "returnOnEquityTTM": 1.5, "evToEBITDATTM": 25.0}]
    ratios = [{"priceToEarningsRatioTTM": 30.0, "priceToBookRatioTTM": 50.0,
               "netProfitMarginTTM": 0.25, "grossProfitMarginTTM": 0.46,
               "priceToEarningsGrowthRatioTTM": 2.0}]
    grades = [{"gradingCompany": "Morgan Stanley", "newGrade": "Overweight",
               "action": "maintain", "date": "2026-06-10"}]
    f = fmp._montar_fundamentos(km, ratios, grades)
    assert f["pe"] == 30.0 and f["roe"] == 1.5 and f["margem_liquida"] == 0.25
    assert f["ev_ebitda"] == 25.0 and f["market_cap"] == 3.5e12
    assert f["ultima_recomendacao"]["empresa"] == "Morgan Stanley"
    assert f["ultima_recomendacao"]["nota"] == "Overweight"


def test_montar_fundamentos_tolera_vazio():
    f = fmp._montar_fundamentos([], [], [])
    assert f["pe"] is None and f["roe"] is None and f["ultima_recomendacao"] is None


def test_fmp_get_sem_chave_retorna_none(monkeypatch):
    monkeypatch.setattr(fmp, "_key", lambda: None)
    assert fmp.fmp_get("quote", symbol="AAPL") is None


def test_fundamentos_sem_chave_retorna_none(monkeypatch):
    monkeypatch.setattr(fmp, "_key", lambda: None)
    assert fmp.fundamentos("AAPL") is None
