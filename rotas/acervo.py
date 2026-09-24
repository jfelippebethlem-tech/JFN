# -*- coding: utf-8 -*-
"""Rotas do ACERVO: busca única e ficha completa de qualquer processo (Estado ou Prefeitura)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/acervo/buscar")
async def api_acervo_buscar(q: str = "", esfera: str = "todos", limite: int = 60):
    from compliance_agent.acervo import buscar
    r = await asyncio.to_thread(buscar, q, esfera, limite)
    return JSONResponse(content=r, status_code=200 if r.get("ok") else 400)


@router.get("/api/acervo/processo")
async def api_acervo_processo(numero: str = ""):
    from compliance_agent.acervo import ficha
    r = await asyncio.to_thread(ficha, numero)
    return JSONResponse(content=r, status_code=200 if r.get("ok") else 400)


@router.get("/api/acervo/documento")
async def api_acervo_documento(numero: str = "", seq: str = ""):
    from compliance_agent.acervo import texto_documento
    r = await asyncio.to_thread(texto_documento, numero, seq)
    return JSONResponse(content=r, status_code=200 if r.get("ok") else 404)


_EST: dict = {}


@router.get("/api/acervo/estatisticas")
async def api_acervo_estatisticas():
    """Cache de 1 h (o prewarm de 30 min o mantém quente): count(DISTINCT) no SIAFE custava 15–25 s a frio."""
    import time
    from compliance_agent.acervo import estatisticas
    if _EST and time.time() - _EST["t"] < 3600:
        return JSONResponse(content=_EST["v"])
    v = {"ok": True, **(await asyncio.to_thread(estatisticas))}
    _EST.update(t=time.time(), v=v)
    return JSONResponse(content=v)
