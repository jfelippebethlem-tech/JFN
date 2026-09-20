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


@router.get("/api/acervo/estatisticas")
async def api_acervo_estatisticas():
    from compliance_agent.acervo import estatisticas
    return JSONResponse(content={"ok": True, **(await asyncio.to_thread(estatisticas))})
