# -*- coding: utf-8 -*-
"""Rotas massare do JFN — extraído de server.py (split 2026-07-06; rede: tests/test_server_snapshot.py).
Handlers idênticos aos originais; só o decorador mudou de @app p/ @router."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()

@router.get("/api/massare/focus")
async def api_massare_focus(ano: str = ""):
    """Onda 8 — Boletim Focus (BCB/Olinda): Selic/IPCA/PIB/câmbio (mediana), sem chave."""
    try:
        from massare.focus import boletim
        return JSONResponse(content=boletim(ano or None))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/massare/calendario")
async def api_massare_calendario(dias: int = 7):
    """Onda 8 — Agenda macro (CPI/NFP/FOMC/COPOM/PMI China) via Finnhub (chave grátis)."""
    try:
        from massare.calendar import agenda
        return JSONResponse(content=agenda(dias))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/massare/fundamentos")
async def api_massare_fundamentos(ticker: str):
    """Onda 8 — Fundamentos de ação BR (P/L, DY, ROE) via brapi.dev."""
    try:
        from massare.fundamentos import fundamentos
        return JSONResponse(content=fundamentos(ticker))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/massare/noticias")
async def api_massare_noticias(tema: str = "", janela: str = "2d"):
    """Onda 8 — Notícias/narrativas de mercado (GDELT, sem chave). Sem tema = boletim multi-tema."""
    try:
        from massare import news
        return JSONResponse(content=news.coletar(tema, janela) if tema else news.boletim_temas(janela=janela))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/massare/teses")
async def api_massare_teses(registrar: bool = True):
    """Onda 9 — Teses de mercado: narrativa→ativos→direção, registradas como previsão (OOS)."""
    try:
        from massare.theses import atual
        return JSONResponse(content=atual(registrar=registrar))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/massare/carteira")
async def api_massare_carteira():
    """Onda 9 — Carteira manual (data/carteira.json) valorizada + cruzada com teses. Sem broker."""
    try:
        from massare.carteira import carteira
        return JSONResponse(content=carteira())
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/massare/regime")
async def api_massare_regime(symbol: str = "^GSPC"):
    """Regime de mercado (clima) via HMM gaussiano sobre (retorno, vol): calmo-alta (bull) / calmo-baixa
    (bear) / estresse-alta-vol. Não prevê preço — classifica o ambiente p/ condicionar a leitura.
    Aceita NOME amigável (ibovespa, bitcoin, ouro…). Honesto: estados latentes, não certeza."""
    try:
        from massare import ml, market, store
        store.init_db()
        sym = market.resolver_symbol((symbol or "^GSPC").strip())
        try:
            market._refresh_precos([sym])
        except Exception:  # noqa: BLE001
            pass
        return JSONResponse(content={"ok": True, "symbol": sym, "regime": ml.regime_hmm(sym)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/massare/placar")
async def api_massare_placar():
    """Acurácia out-of-sample acumulada + sentimento de mercado (Fear&Greed/VIX)."""
    try:
        from massare import learning, behavior, store, backtest
        store.init_db()
        # HONESTIDADE: o diário de previsões logadas costuma estar pendente (alvo no futuro).
        # O backtest OOS (walk-forward em TODOS os pregões) é o track record honesto: hit-rate
        # vs. piso ingênuo (taxa-base) e o EDGE real. None se o backtest ainda não rodou.
        return JSONResponse({"ok": True, "placar": learning.scoreboard(),
                             "backtest_oos": backtest.resumo_overall(),
                             "sentimento": behavior.snapshot()})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/massare/cenarios")
async def api_massare_cenarios(recalcular: bool = False):
    """
    Último snapshot multi-horizonte do pregão (curtíssimo/curto/médio/longo).
    Por padrão lê o snapshot salvo pelo `massare-market.timer` (rápido). `?recalcular=true` recomputa na hora.
    """
    try:
        from massare import market
        snap = market.cenarios() if recalcular else (market.ler_snapshot() or market.cenarios())
        return JSONResponse({"ok": True, "snapshot": snap, "briefing": market.briefing(snap)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/briefing/dados")
async def api_briefing_dados():
    """Dados confiáveis para a rotina BOM DIA: clima (Open-Meteo) + mercado (Massare) + notícias (Google News
    RSS). O Yoda chama isto em vez de raspar HTML frágil (climatempo/g1/infomoney, que falhavam)."""
    try:
        from compliance_agent.briefing import dados
        return JSONResponse(dados())
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.post("/api/massare/prever")
async def api_massare_prever(payload: Optional[dict] = None):
    """Previsão direcional + estado atual de um ativo. Body: {"symbol":"prata|^BVSP|SI=F","horizon":5}.
    Aceita NOME amigável (prata, ouro, bitcoin…) — resolve p/ o símbolo certo (corrige o 'XAG=F' do Yoda)."""
    payload = payload or {}
    termo = (payload.get("symbol") or payload.get("ativo") or "^BVSP").strip()
    try:
        horizon = int(payload.get("horizon") or 5)
    except (TypeError, ValueError):
        horizon = 5
    try:
        from massare import engine, engine_regime4, store, market
        store.init_db()
        symbol = market.resolver_symbol(termo)  # prata→SI=F, ouro→GC=F, etc.
        try:
            market._refresh_precos([symbol])  # garante dados mesmo fora do núcleo diário (ex.: prata)
        except Exception:  # noqa: BLE001
            pass
        # motor 4-regimes+drift (edge OOS do universo ≥0); cai p/ o ensemble global se faltar dado
        p = engine_regime4.predict_today(symbol, horizon=horizon) or engine.predict_today(symbol, horizon=horizon)
        if not p:
            return JSONResponse({"ok": False, "erro": f"Sem dados para {termo} ({symbol}).",
                                 "dica": "símbolos: prata=SI=F, ouro=GC=F, bitcoin=BTC-USD, ibovespa=^BVSP"},
                                status_code=404)
        # estado ATUAL (preço + variação) para responder "como está hoje"
        atual = {}
        try:
            df = engine.load_prices(symbol)
            if df is not None and len(df) >= 2:
                ult, ant = float(df["close"].iloc[-1]), float(df["close"].iloc[-2])
                atual = {"preco": round(ult, 2), "var_pct": round((ult / ant - 1) * 100, 2) if ant else None}
        except Exception:  # noqa: BLE001
            pass
        return JSONResponse({"ok": True, "ativo": market.NOMES.get(symbol, termo), "symbol": symbol,
                             "atual": atual, "previsao": p})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)
