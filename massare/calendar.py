# -*- coding: utf-8 -*-
"""Calendário macro — JFN 2.0, Onda 8 (Massare; agenda de dados que move mercado).

Eventos macro (CPI/NFP/FOMC/COPOM/PMI China) via Finnhub `/calendar/economic` (chave grátis).
Honesto: SEM FINNHUB_API_KEY → INDISPONÍVEL (nunca fabrica agenda). Onde houver chave, traz
previsto vs anterior por evento.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import httpx


def agenda(dias: int = 7) -> dict:
    """Eventos macro dos próximos `dias`. Requer FINNHUB_API_KEY (grátis). {ok, eventos[]} | INDISPONÍVEL."""
    key = (os.environ.get("FINNHUB_API_KEY") or "").strip()
    if not key:
        return {"ok": True, "eventos": [],
                "_nota": "INDISPONÍVEL: defina FINNHUB_API_KEY (grátis em finnhub.io) p/ a agenda macro. "
                         "Nada foi fabricado.", "_fonte": "Finnhub /calendar/economic"}
    hoje = date.today()
    try:
        r = httpx.get("https://finnhub.io/api/v1/calendar/economic", params={
            "from": hoje.isoformat(), "to": (hoje + timedelta(days=dias)).isoformat(), "token": key,
        }, timeout=25)
        if r.status_code != 200:
            return {"ok": False, "erro": f"Finnhub HTTP {r.status_code}"}
        ev = (r.json() or {}).get("economicCalendar", []) or []
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": f"Finnhub: {str(e)[:80]}"}

    eventos = [{
        "data": e.get("time", "")[:10], "pais": e.get("country"), "evento": e.get("event"),
        "impacto": e.get("impact"), "previsto": e.get("estimate"), "anterior": e.get("prev"),
        "atual": e.get("actual"),
    } for e in ev if (e.get("impact") in ("high", "medium") or not e.get("impact"))]
    return {"ok": True, "n": len(eventos), "eventos": eventos[:60],
            "_fonte": "Finnhub /calendar/economic (free tier)",
            "_nota": "Agenda macro (previsto vs anterior); surpresa = atual − previsto."}
