# -*- coding: utf-8 -*-
"""Rotas hermes do JFN — extraído de server.py (split 2026-07-06; rede: tests/test_server_snapshot.py).
Handlers idênticos aos originais; só o decorador mudou de @app p/ @router."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

from typing import TYPE_CHECKING
if TYPE_CHECKING:  # anotação apenas; import real é lazy nos handlers
    from compliance_agent.hermes_goal import HermesGoalAgent
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

router = APIRouter()

_agent_loop_trabalhar_task: Optional[asyncio.Task] = None

_agent_loop_queue: Optional[asyncio.Queue] = None  # SSE stream


@router.get("/api/hermes/estado")
async def api_hermes_estado():
    """Estado do Hermes: missão, Chrome 9222, contagens e aprendizados recentes."""
    from compliance_agent.database.models import get_session, init_db, OrdemBancaria, Alerta
    from compliance_agent.hermes_goal import HermesGoalAgent, chrome_disponivel
    from compliance_agent.llm.free_llm import openrouter_available, groq_available
    from compliance_agent.llm.memoria import lembrar
    init_db()
    s = get_session()
    try:
        ag = HermesGoalAgent(session=s)
        aprendizados = [m["valor"][:140] for m in lembrar("licao", session=s)[:6]]
        return JSONResponse({
            "missao": ag.missao_atual(),
            "chrome_9222": await chrome_disponivel(),
            "llm_ok": bool(openrouter_available() or groq_available()),
            "n_obs": s.query(OrdemBancaria).count(),
            "n_alertas": s.query(Alerta).count(),
            "aprendizados": aprendizados,
        })
    finally:
        s.close()


@router.post("/api/hermes/missao")
async def api_hermes_definir_missao(payload: dict):
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.hermes_goal import HermesGoalAgent, mission_queue
    init_db()
    s = get_session()
    try:
        texto = (payload or {}).get("missao", "").strip()
        if not texto:
            return JSONResponse({"erro": "missão vazia"}, status_code=400)
        HermesGoalAgent(session=s).definir_missao(texto)
        try:
            import asyncio
            asyncio.create_task(mission_queue.enqueue({"tipo": "missao", "texto": texto}))
        except Exception as exc:
            logger.warning("missão definida mas não enfileirada (fica só no banco, não executa já): %s", exc)
        return JSONResponse({"ok": True, "missao": texto, "queue_size": mission_queue.qsize()})
    finally:
        s.close()


@router.delete("/api/hermes/missao")
async def api_hermes_limpar_missao():
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.hermes_goal import HermesGoalAgent
    init_db()
    s = get_session()
    try:
        HermesGoalAgent(session=s).limpar_missao()
        return JSONResponse({"ok": True})
    finally:
        s.close()


@router.post("/api/hermes/missoes")
async def api_hermes_criar_missao(payload: dict):
    """Cria uma missão paralela e dispara a execução em background."""
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.hermes_goal import criar_missao_paralela
    init_db()
    s = get_session()
    try:
        objetivo = (payload or {}).get("objetivo", "").strip()
        if not objetivo:
            return JSONResponse({"erro": "objetivo vazio"}, status_code=400)
        titulo = (payload or {}).get("titulo", "").strip()
        prioridade = (payload or {}).get("prioridade", "media").strip()
        dados = criar_missao_paralela(objetivo, titulo=titulo,
                                      prioridade=prioridade, session=s)
        return JSONResponse({"ok": True, "missao": dados})
    finally:
        s.close()


@router.get("/api/hermes/missoes")
async def api_hermes_listar_missoes():
    """Lista missões (em execução + histórico), mais recentes primeiro."""
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.hermes_goal import listar_missoes, HermesGoalAgent
    init_db()
    s = get_session()
    try:
        return JSONResponse({
            "ok": True,
            "missoes": listar_missoes(session=s),
            "em_execucao": HermesGoalAgent.running_missions(),
        })
    finally:
        s.close()


@router.get("/api/hermes/missoes/{missao_id}")
async def api_hermes_detalhe_missao(missao_id: int):
    """Detalhe de uma missão específica."""
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.hermes_goal import detalhe_missao
    init_db()
    s = get_session()
    try:
        d = detalhe_missao(missao_id, session=s)
        if not d:
            return JSONResponse({"erro": "missão não encontrada"}, status_code=404)
        return JSONResponse({"ok": True, "missao": d})
    finally:
        s.close()


_agent_loop_lock = asyncio.Lock()


async def _trabalhar_loop_until_done(ag: "HermesGoalAgent"):
    loop_fim = asyncio.Event()
    n_passos = 0
    ultimo_aprendizado = ""
    while not loop_fim.is_set():
        ciclo = await ag.trabalhar()
        n_passos += len(ciclo.get("passos", []))
        for item in ciclo.get("passos", []):
            payload = {
                "acao": item.get("acao"),
                "pensamento": item.get("pensamento"),
                "resultado": item.get("resultado"),
            }
            if _agent_loop_queue:
                await _agent_loop_queue.put(payload)
        if ciclo.get("resumo"):
            ultimo_aprendizado = str(ciclo.get("resumo"))
        if ciclo.get("concluido") or ciclo.get("erro"):
            break
        await asyncio.sleep(1)
    if _agent_loop_queue:
        await _agent_loop_queue.put({
            "acao": "concluir",
            "pensamento": "Ciclo autônomo finalizado",
            "resultado": {"resumo": ultimo_aprendizado or "Missão processada."},
        })


async def _cancelar_loop_trabalhar():
    global _agent_loop_trabalhar_task
    async with _agent_loop_lock:
        if _agent_loop_trabalhar_task and not _agent_loop_trabalhar_task.done():
            _agent_loop_trabalhar_task.cancel()
            try:
                await _agent_loop_trabalhar_task
            except asyncio.CancelledError:
                pass
            _agent_loop_trabalhar_task = None


@router.post("/api/hermes/trabalhar")
async def api_hermes_trabalhar():
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.hermes_goal import HermesGoalAgent
    init_db()
    s = get_session()
    try:
        ag = HermesGoalAgent(session=s)
        if not ag.missao_atual():
            return JSONResponse({"erro": "Defina uma missão antes de trabalhar."})
        await _cancelar_loop_trabalhar()
        _agent_loop_queue = asyncio.Queue()
        loop_task = asyncio.create_task(_trabalhar_loop_until_done(ag))
        _agent_loop_trabalhar_task = loop_task
        return JSONResponse({"ok": True, "status": "trabalhando"})
    except Exception as e:
        return JSONResponse({"erro": f"{type(e).__name__}: {e}"})
    finally:
        s.close()


@router.get("/api/hermes/stream")
async def api_hermes_stream():
    async def event_stream():
        while True:
            if _agent_loop_queue is None:
                await asyncio.sleep(0.25)
                continue
            try:
                item = await _agent_loop_queue.get()
            except asyncio.CancelledError:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/api/hermes/parar")
@router.post("/api/hermes/parar")
async def api_hermes_parar(payload: Optional[dict] = None):
    """Para o ciclo 'trabalhar agora' em andamento."""
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.hermes_goal import HermesGoalAgent, mission_queue
    init_db()
    s = get_session()
    try:
        await _cancelar_loop_trabalhar()
        try:
            for _ in range(min(20, mission_queue.qsize())):
                try:
                    mission_queue.dequeue_nowait()
                except Exception:
                    break
            while not mission_queue.empty():
                mission_queue.dequeue_nowait()
        except Exception as exc:
            logger.debug("limpeza da fila de missões interrompida: %s", exc)
        HermesGoalAgent(session=s).limpar_missao()
        return JSONResponse({"ok": True, "status": "parado"})
    except Exception as e:
        return JSONResponse({"erro": f"{type(e).__name__}: {e}"}, status_code=500)
    finally:
        s.close()


@router.post("/api/hermes/chat")
async def api_hermes_chat(payload: dict):
    """Conversa com o Hermes (raciocínio profundo sobre os casos)."""


@router.post("/api/hermes/auditor24h/iniciar")
async def api_auditor24h_iniciar(payload: Optional[dict] = None):
    """Liga o modo Auditor 24 horas (botão da interface)."""
    from compliance_agent.hermes_goal import iniciar_auditor_24h
    objetivo = ((payload or {}).get("objetivo") or "").strip()
    intervalo = (payload or {}).get("intervalo_seg")
    try:
        intervalo = int(intervalo) if intervalo else None
    except (TypeError, ValueError):
        intervalo = None
    try:
        return JSONResponse(iniciar_auditor_24h(objetivo=objetivo, intervalo_seg=intervalo))
    except Exception as e:
        return JSONResponse({"ok": False, "erro": f"{type(e).__name__}: {e}"})


@router.post("/api/hermes/auditor24h/parar")
async def api_auditor24h_parar():
    """Desliga o modo Auditor 24 horas."""
    from compliance_agent.hermes_goal import parar_auditor_24h
    try:
        return JSONResponse(parar_auditor_24h())
    except Exception as e:
        return JSONResponse({"ok": False, "erro": f"{type(e).__name__}: {e}"})


@router.get("/api/hermes/auditor24h/status")
async def api_auditor24h_status():
    """Estado atual do Auditor 24 horas (ciclos, último resumo, etc.)."""
    from compliance_agent.hermes_goal import status_auditor_24h
    try:
        return JSONResponse(status_auditor_24h())
    except Exception as e:
        return JSONResponse({"ativo": False, "erro": f"{type(e).__name__}: {e}"})


@router.post("/api/hermes/relatorio")
async def api_hermes_relatorio(payload: Optional[dict] = None):
    from compliance_agent.reporting.export_relatorios import generate_report
    fmt = ((payload or {}).get("formato") or "txt").strip().lower()
    result = generate_report(fmt=fmt)
    return JSONResponse(result)
