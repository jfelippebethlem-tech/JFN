# -*- coding: utf-8 -*-
"""Fundamentos de ação BR — JFN 2.0, Onda 8 (Massare camada fundamentalista).

brapi.dev: preço + fundamentos CVM (P/L, DY, ROE, balanços) de uma ação da B3. Free tier
(funciona p/ algumas ações sem token; BRAPI_TOKEN grátis amplia a cobertura).

Honesto: sem cobertura/sem token p/ o ticker → INDISPONÍVEL (nunca fabrica indicador).
"""
from __future__ import annotations

import os

import httpx


def _via_fmp(ticker: str) -> dict | None:
    """Fallback p/ ações US (e qualquer ticker que a brapi não cobre): FMP via chave grátis. None se vazio."""
    try:
        from massare import fmp
        f = fmp.fundamentos(ticker)
    except Exception:  # noqa: BLE001
        return None
    if not f or (f.get("pe") is None and f.get("roe") is None):
        return None
    rec = f.get("ultima_recomendacao") or {}
    return {
        "ok": True, "ticker": ticker, "preco": None,
        "pl": f.get("pe"), "dy": None, "roe": f.get("roe"),
        "margem_liquida": f.get("margem_liquida"), "ev_ebitda": f.get("ev_ebitda"),
        "market_cap": f.get("market_cap"),
        "recomendacao": (f"{rec.get('empresa')} → {rec.get('nota')}" if rec.get("empresa") else None),
        "nome": ticker,
        "_fonte": "FMP /stable (chave grátis) — fundamentos US TTM",
        "_nota": "Indicadores fundamentalistas (TTM); não é recomendação de compra/venda.",
    }


def fundamentos(ticker: str) -> dict:
    """P/L, DY, ROE, preço. Ação B3 → brapi.dev (CVM); ticker US/sem cobertura → fallback FMP. INDISPONÍVEL honesto."""
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return {"ok": False, "erro": "informe o ticker (ex.: PETR4)"}
    params = {"modules": "defaultKeyStatistics,financialData", "fundamental": "true"}
    token = (os.environ.get("BRAPI_TOKEN") or os.environ.get("BRAPI_API_KEY") or "").strip()
    if token:
        params["token"] = token
    res = []
    try:
        r = httpx.get(f"https://brapi.dev/api/quote/{ticker}", params=params,
                      headers={"User-Agent": "JFN-Massare/2.0"}, timeout=25)
        if r.status_code == 200:
            res = (r.json() or {}).get("results", []) or []
    except Exception:  # noqa: BLE001 — sem brapi, tenta FMP abaixo
        res = []
    q = res[0] if res else {}
    pl = q.get("priceEarnings") or (q.get("defaultKeyStatistics") or {}).get("forwardPE")
    roe = (q.get("financialData") or {}).get("returnOnEquity")
    if pl is not None or roe is not None:  # brapi cobriu (ação BR)
        return {
            "ok": True, "ticker": ticker, "preco": q.get("regularMarketPrice"),
            "pl": pl, "dy": q.get("dividendYield") or (q.get("defaultKeyStatistics") or {}).get("dividendYield"),
            "roe": roe, "nome": q.get("longName") or q.get("shortName"),
            "_fonte": "brapi.dev (fundamentos CVM)",
            "_nota": "Indicadores fundamentalistas; não é recomendação de compra/venda.",
        }
    fmp_out = _via_fmp(ticker)  # ticker US ou brapi sem cobertura
    if fmp_out:
        return fmp_out
    return {"ok": True, "ticker": ticker,
            "_nota": "INDISPONÍVEL: sem cobertura na brapi (BR) nem na FMP (US). Nada fabricado.",
            "_fonte": "brapi.dev / FMP"}
