# -*- coding: utf-8 -*-
"""fundamentos(): ação BR via brapi; ticker US cai no fallback FMP (sem rede no teste)."""
from __future__ import annotations

from massare import fundamentos as F


def test_us_ticker_cai_no_fallback_fmp(monkeypatch):
    # brapi não cobre (simula resposta vazia) e o FMP responde → resultado vem do FMP
    class _R:
        status_code = 200
        def json(self):
            return {"results": []}
    monkeypatch.setattr(F.httpx, "get", lambda *a, **k: _R())
    from massare import fmp
    monkeypatch.setattr(fmp, "fundamentos", lambda s: {
        "pe": 31.17, "roe": 1.11, "margem_liquida": 0.63, "ev_ebitda": 25.7,
        "market_cap": 4.2e12, "ultima_recomendacao": {"empresa": "Needham", "nota": "Buy"}})
    out = F.fundamentos("NVDA")
    assert out["ok"] and out["pl"] == 31.17 and out["roe"] == 1.11
    assert "Needham" in out["recomendacao"] and "FMP" in out["_fonte"]


def test_sem_cobertura_nenhuma_e_indisponivel(monkeypatch):
    class _R:
        status_code = 200
        def json(self):
            return {"results": []}
    monkeypatch.setattr(F.httpx, "get", lambda *a, **k: _R())
    from massare import fmp
    monkeypatch.setattr(fmp, "fundamentos", lambda s: None)
    out = F.fundamentos("ZZZZ")
    assert out["ok"] and "INDISPONÍVEL" in out["_nota"]


def test_br_ticker_usa_brapi(monkeypatch):
    class _R:
        status_code = 200
        def json(self):
            return {"results": [{"priceEarnings": 8.5, "regularMarketPrice": 38.0,
                                 "financialData": {"returnOnEquity": 0.22}, "longName": "Petrobras"}]}
    monkeypatch.setattr(F.httpx, "get", lambda *a, **k: _R())
    out = F.fundamentos("PETR4")
    assert out["pl"] == 8.5 and out["roe"] == 0.22 and "brapi" in out["_fonte"]
