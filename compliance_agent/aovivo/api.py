# -*- coding: utf-8 -*-
"""API do AO VIVO (só leitura; não existe rota para ligar/desligar motor).

    GET /api/ao-vivo/estado   snapshot: motores (estado, desde, próxima, progresso, atividade 60 min),
                              últimos eventos, eventos/min, resumo
    GET /api/ao-vivo/stream   SSE (`text/event-stream`): `event: estado` quando algo muda, `event: evento`
                              a cada evento novo, comentário `: hb` de batimento a cada 15 s; reconexão
                              com `Last-Event-ID` reenvia o que o cliente perdeu (anel de 240 eventos)

Autenticação = middleware `_auth_jfn` do `server.py` (cookie do painel), como todo `/api/*`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from compliance_agent.aovivo.coleta import INTERVALO, coletor

router = APIRouter()
BATIMENTO = 15.0


def snapshot() -> dict:
    return coletor().snapshot()


@router.get("/api/ao-vivo/estado")
def ao_vivo_estado():
    return snapshot()


@router.get("/api/ao-vivo/claude")
def ao_vivo_claude():
    """Uso do co-motor Claude hoje: chamadas, por tarefa, tetos, último erro, canário (sem conteúdo)."""
    from compliance_agent.aovivo.coleta import ler_uso
    return ler_uso("claude_motor") or {"disponivel": False}


@router.get("/api/ao-vivo/cruzamento")
def ao_vivo_cruzamento(dias: int = 30):
    """Bloco "Cruzamento de motores": concordância com o Claude por tarefa × modelo, matriz ⚪🟡🔴, A/B do
    few-shot, revisões pendentes (divergência grave). Acordo com o Claude é referência, não gabarito."""
    from compliance_agent.llm.cruzamento import resumo_painel
    return resumo_painel(max(1, min(int(dias), 365)))


def _sse(evento: str, dado: dict, id_: int | None = None) -> str:
    cab = f"id: {id_}\n" if id_ is not None else ""
    return f"{cab}event: {evento}\ndata: {json.dumps(dado, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _assinatura(motores: list[dict]) -> str:
    return hashlib.sha1(json.dumps([(m["id"], m["estado"], m["progresso"], m["proxima"]) for m in motores]).encode()).hexdigest()


async def gerar(request: Request, ultimo_id: int = 0, max_ciclos: int | None = None):
    """Gerador do SSE. `max_ciclos` existe só para teste (em produção roda até o cliente sair)."""
    c = coletor()
    yield "retry: 5000\n\n"
    snap = await asyncio.to_thread(c.snapshot)
    visto = ultimo_id
    if ultimo_id:                                   # reconexão: só o que o cliente perdeu
        snap = dict(snap, eventos=c.eventos_publicos(depois_de=ultimo_id))
    yield _sse("estado", snap)
    for e in snap["eventos"]:
        visto = max(visto, e["id"])
    assin, t_hb, ciclos = _assinatura(c.motores), time.time(), 0
    while max_ciclos is None or ciclos < max_ciclos:
        ciclos += 1
        if await request.is_disconnected():
            break
        await asyncio.sleep(INTERVALO if max_ciclos is None else 0)
        await asyncio.to_thread(c.tick)
        for e in c.eventos_publicos(depois_de=visto):
            visto = max(visto, e["id"])
            yield _sse("evento", e, e["id"])
        nova = _assinatura(c.motores)
        if nova != assin:
            assin = nova
            yield _sse("estado", dict(c.snapshot(), eventos=[]))
        if time.time() - t_hb >= BATIMENTO:
            t_hb = time.time()
            yield ": hb\n\n"


@router.get("/api/ao-vivo/stream")
async def ao_vivo_stream(request: Request):
    try:
        ultimo = int(request.headers.get("last-event-id") or 0)
    except ValueError:
        ultimo = 0
    return StreamingResponse(gerar(request, ultimo), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
