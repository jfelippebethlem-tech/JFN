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


@router.get("/api/casos")
async def api_casos():
    """Os dossiês do vault (casos conferidos à mão), com o parecer do Processo 360 dos autos que citam."""
    from compliance_agent.casos_vault import listar
    r = await asyncio.to_thread(listar)
    return JSONResponse(content=r, status_code=200 if r.get("ok") else 503)


@router.get("/api/casos/nota")
async def api_casos_nota(slug: str = ""):
    from compliance_agent.casos_vault import nota
    r = await asyncio.to_thread(nota, slug)
    return JSONResponse(content=r, status_code=200 if r.get("ok") else 404)


@router.get("/api/galaxia")
async def api_galaxia(request: Request, limite: int = 0, score_min: int = 0, orgao: str = ""):
    """Galáxia dos casos: órgãos, fornecedores do Radar e de alertas abertos, dossiês do vault, sócios (QSA
    público) e processos SEI, com as ligações reais. JSON pré-calculado (`data/cache/galaxia.json`, gerado pela
    ronda); `limite`/`score_min`/`orgao` recortam. Ligação = indício de relação a conferir, nunca prova."""
    from fastapi.responses import Response
    from compliance_agent.galaxia import galaxia_bytes, galaxia_gz
    gz = "gzip" in request.headers.get("accept-encoding", "")
    args = (max(0, min(limite, 20000)) or None, max(0, min(score_min, 100)), orgao[:80])
    try:
        b = await asyncio.to_thread(galaxia_gz if gz else galaxia_bytes, *args)
    except Exception as exc:  # noqa: BLE001 — a página mostra "indisponível", nunca grafo vazio fingido
        return JSONResponse({"ok": False, "erro": f"galáxia indisponível: {type(exc).__name__}"}, status_code=503)
    h = {"Cache-Control": "private, max-age=60", "Vary": "Accept-Encoding"}
    if gz:
        h["Content-Encoding"] = "gzip"            # já comprimido e memorizado: o GZipMiddleware não recomprime
    return Response(content=b, media_type="application/json", headers=h)


@router.get("/api/galaxia/no")
async def api_galaxia_no(id: str = ""):
    """Um nó da galáxia com a prova (sinais do Radar, alertas abertos, dossiês) e o motivo de cada ligação."""
    from compliance_agent.galaxia import detalhe
    r = await asyncio.to_thread(detalhe, id[:200])
    return JSONResponse(content=r, status_code=200 if r.get("ok") else 404)


@router.get("/api/requerimentos")
async def api_requerimentos():
    """Os requerimentos de informação sugeridos pelas investigações (notas do vault) — só leitura."""
    from compliance_agent.requerimentos_vault import listar
    r = await asyncio.to_thread(listar)
    return JSONResponse(content=r, status_code=200 if r.get("ok") else 503)


@router.get("/api/requerimentos/minuta")
async def api_requerimentos_minuta(slug: str = ""):
    from compliance_agent.requerimentos_vault import minuta
    r = await asyncio.to_thread(minuta, slug)
    return JSONResponse(content=r, status_code=200 if r.get("ok") else 404)


_EST: dict = {}


@router.get("/api/acervo/estatisticas")
async def api_acervo_estatisticas():
    """Visão materializada `acervo_estatisticas` (E15, O7.1: sem TTL); ausente → cálculo legado abaixo."""
    from compliance_agent.aplicacao.estagios import materializar as M
    if (pronta := M.resposta("acervo_estatisticas")) is not None:
        return pronta
    return M.marcar_ausente(await _api_acervo_estatisticas_legado(), "acervo_estatisticas")


async def _api_acervo_estatisticas_legado():
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
