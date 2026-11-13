# -*- coding: utf-8 -*-
"""Rota da sub-aba "Governo Couto" — Estado › Governo Couto (gestão do governador em exercício desde 23/03/2026)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/governo_couto")
def api_governo_couto():
    """Placar, atos do DOERJ, contratações, OB do SIAFE, controle e pontos de atenção do período — cada bloco com
    fonte e cobertura. Só leitura. A parte de base passa pelo cache SWR do painel (1 h; o prewarm de 30 min a mantém
    quente); os pontos de atenção são relidos do arquivo a cada chamada."""
    from compliance_agent import governo_couto as G
    from rotas.investigacao import _cache_calc
    try:
        pesado = _cache_calc("governo_couto:base", 3600, G._pesado)
        return JSONResponse(G.montar(pesado=pesado))
    except (sqlite3.Error, OSError, ValueError, KeyError) as exc:   # a tela mostra o erro em vez de travar
        return JSONResponse({"ok": False, "erro": f"{type(exc).__name__}: {exc}"}, status_code=500)
