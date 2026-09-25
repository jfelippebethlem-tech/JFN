# -*- coding: utf-8 -*-
"""Rotas do ACERVO: busca única e ficha completa de qualquer processo (Estado ou Prefeitura)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
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


@router.get("/api/acervo/regras")
async def api_acervo_regras(limite: int = 300):
    """Processos com regra determinística acesa no acervo inteiro (a leitura processo a processo virou regra)."""
    from compliance_agent.acervo import regras_acesas
    return JSONResponse(content=await asyncio.to_thread(regras_acesas, max(1, min(int(limite or 300), 2000))))


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


@router.post("/api/pcrj/consultar")
async def api_pcrj_consultar(req: Request):
    """Consulta ao vivo de processo da Prefeitura na pesquisa pública do SEI.RIO (executada na VM-2)."""
    from compliance_agent.acervo import pedir_consulta_pcrj
    try:
        body = await req.json()
    except ValueError:
        body = {}
    return JSONResponse(content=pedir_consulta_pcrj(str((body or {}).get("numero") or "")))
