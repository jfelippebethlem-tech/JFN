# -*- coding: utf-8 -*-
"""Fundamentos de ação BR — JFN 2.0, Onda 8 (Massare camada fundamentalista).

brapi.dev: preço + fundamentos CVM (P/L, DY, ROE, balanços) de uma ação da B3. Free tier
(funciona p/ algumas ações sem token; BRAPI_TOKEN grátis amplia a cobertura).

Honesto: sem cobertura/sem token p/ o ticker → INDISPONÍVEL (nunca fabrica indicador).
"""
from __future__ import annotations

import os

import httpx


def fundamentos(ticker: str) -> dict:
    """P/L, DY, ROE, preço de uma ação B3 (brapi.dev). {ok, ticker, preco, pl, dy, roe} | INDISPONÍVEL."""
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return {"ok": False, "erro": "informe o ticker (ex.: PETR4)"}
    params = {"modules": "defaultKeyStatistics,financialData", "fundamental": "true"}
    token = (os.environ.get("BRAPI_TOKEN") or os.environ.get("BRAPI_API_KEY") or "").strip()
    if token:
        params["token"] = token
    try:
        r = httpx.get(f"https://brapi.dev/api/quote/{ticker}", params=params,
                      headers={"User-Agent": "JFN-Massare/2.0"}, timeout=25)
        if r.status_code != 200:
            return {"ok": True, "ticker": ticker,
                    "_nota": f"INDISPONÍVEL: brapi HTTP {r.status_code} (token grátis amplia cobertura). Nada fabricado.",
                    "_fonte": "brapi.dev"}
        res = (r.json() or {}).get("results", []) or []
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": f"brapi: {str(e)[:80]}"}
    if not res:
        return {"ok": True, "ticker": ticker, "_nota": "INDISPONÍVEL: sem dados p/ o ticker.", "_fonte": "brapi.dev"}
    q = res[0]
    dks = q.get("defaultKeyStatistics") or {}
    fin = q.get("financialData") or {}
    return {
        "ok": True, "ticker": ticker,
        "preco": q.get("regularMarketPrice"),
        "pl": q.get("priceEarnings") or dks.get("forwardPE"),
        "dy": q.get("dividendYield") or dks.get("dividendYield"),
        "roe": fin.get("returnOnEquity"),
        "nome": q.get("longName") or q.get("shortName"),
        "_fonte": "brapi.dev (fundamentos CVM)",
        "_nota": "Indicadores fundamentalistas; não é recomendação de compra/venda.",
    }
