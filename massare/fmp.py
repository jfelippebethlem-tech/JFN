# -*- coding: utf-8 -*-
"""
FMP (Financial Modeling Prep) — sinais via chave GRÁTIS (`/stable`), para o serviço autônomo do Massare.

Cobertura GRÁTIS confirmada (2026-06-11) com a chave do dono: quote, profile, historical-price, income-
statement, ratios-ttm, key-metrics-ttm, earnings-calendar, grades (recomendações de analistas).

PREMIUM (pago, 402 "Restricted") na chave grátis: insider, senate/congresso, 13F, calendário macro,
técnicos, notícias. Esses sinais diferenciados vêm pelo MCP do FMP (materializados à parte em massare.db) —
NÃO por aqui. Honesto: sem chave/indisponível → None (o chamador decide), nunca número fabricado.
"""
from __future__ import annotations

import os

import httpx

_BASE = "https://financialmodelingprep.com/stable"


def _key() -> str | None:
    k = os.environ.get("FMP_API_KEY")
    if k:
        return k
    try:
        from pathlib import Path

        from dotenv import dotenv_values
        for p in (Path.home() / "JFN" / ".env", Path.home() / ".hermes" / ".env"):
            if p.exists():
                v = dotenv_values(p).get("FMP_API_KEY")
                if v:
                    return v
    except Exception:  # noqa: BLE001
        pass
    return None


def fmp_get(path: str, **params):
    """GET no FMP /stable com a chave grátis. None se sem chave ou falha (degrada honesto)."""
    key = _key()
    if not key:
        return None
    params["apikey"] = key
    try:
        r = httpx.get(f"{_BASE}/{path}", params=params, timeout=20)
        if r.status_code == 200:
            return r.json()
    except Exception:  # noqa: BLE001
        pass
    return None


def _num(d: dict | None, k: str):
    v = (d or {}).get(k)
    try:
        return round(float(v), 4) if v is not None else None
    except (TypeError, ValueError):
        return None


def _montar_fundamentos(km, ratios, grades) -> dict:
    """Núcleo PURO: normaliza key-metrics-ttm + ratios-ttm + grades em fundamentos enxutos."""
    km = (km[0] if isinstance(km, list) and km else km) or {}
    ratios = (ratios[0] if isinstance(ratios, list) and ratios else ratios) or {}
    grade = None
    if isinstance(grades, list) and grades:
        g = grades[0]
        grade = {"empresa": g.get("gradingCompany"), "nota": g.get("newGrade"),
                 "acao": g.get("action"), "data": g.get("date")}
    return {
        "pe": _num(ratios, "priceToEarningsRatioTTM"),
        "peg": _num(ratios, "priceToEarningsGrowthRatioTTM"),
        "pb": _num(ratios, "priceToBookRatioTTM"),
        "margem_liquida": _num(ratios, "netProfitMarginTTM"),
        "margem_bruta": _num(ratios, "grossProfitMarginTTM"),
        "roe": _num(km, "returnOnEquityTTM"),
        "ev_ebitda": _num(km, "evToEBITDATTM"),
        "market_cap": _num(km, "marketCap"),
        "ultima_recomendacao": grade,
        "_fonte": "FMP /stable (chave grátis)",
    }


def fundamentos(symbol: str) -> dict | None:
    """Fundamentos TTM de um ticker (PE/PEG/P-B/margens/ROE/EV-EBITDA + última recomendação de analista).

    Funciona no serviço autônomo (chave grátis). None se sem chave/indisponível (honesto)."""
    km = fmp_get("key-metrics-ttm", symbol=symbol)
    if km is None:
        return None
    ratios = fmp_get("ratios-ttm", symbol=symbol)
    grades = fmp_get("grades", symbol=symbol)
    out = _montar_fundamentos(km, ratios, grades)
    out["symbol"] = symbol
    return out


if __name__ == "__main__":
    import json
    import sys
    for s in sys.argv[1:] or ["AAPL"]:
        print(json.dumps(fundamentos(s), ensure_ascii=False, indent=2, default=str))
