# -*- coding: utf-8 -*-
"""Radar de vigilância (`/api/radar/*`) e a ponte HTTP do núcleo (`POST /api/nucleo/comando`, usada pelo Yoda).

Saiu de `rotas/investigacao.py` na O7.6 (2026-11-25), sem mudar comportamento: mesmas rotas, mesmos corpos.
O cache do painel e os ajudantes (`_ro`, `_cache_calc`…) continuam em `rotas/investigacao.py` e são importados de lá
(o materializador e os testes redirecionam aqueles nomes naquele módulo)."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse


router = APIRouter()


@router.post("/api/radar/vigiar")
def api_radar_vigiar(payload: Optional[dict] = None):
    """Onda 6 — Radar: adiciona um alvo à watchlist 24/7. Body {"alvo","tipo":cnpj|ug|nome|objeto}.
    Ao surgir edital aberto restritivo / OB anômala do alvo, chega alerta no Telegram."""
    try:
        from compliance_agent.radar import vigiar

        p = payload or {}
        return JSONResponse(content=vigiar(p.get("alvo", ""), p.get("tipo", "cnpj")))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/radar/status")
def api_radar_status():
    """Onda 6 — Radar: o que está sendo vigiado + últimos alertas."""
    try:
        from compliance_agent.radar import status as radar_status

        return JSONResponse(content=radar_status())
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.post("/api/radar/ciclo")
async def api_radar_ciclo():
    """Onda 6 — Radar: roda um ciclo de vigilância agora (o timer systemd chama isto)."""
    try:
        from compliance_agent.radar import ciclo

        return JSONResponse(content=await ciclo())
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.post("/api/nucleo/comando")
async def api_nucleo_comando(payload: dict = None):
    """Núcleo de perícia INTERATIVO (/pericia, /veredito, /placar, /fantasma, /fases, /promover,
    /ciclo_nucleo, /fornecedor, /parametros, /evolucao) — religa o núcleo ao Yoda vivo (gateway).
    Os handlers só existiam no bot de comandos DESATIVADO (yoda.service, 2026-06-06); o lado batch
    (timer 06:30) vivia, mas o interativo/feedback humano estava inalcançável (achado 2026-07-11).

    payload: {comando: "/pericia", args: "..."} OU {texto: "pericia a MGS Clean"} (roteador
    determinístico interpretar_texto_livre, sem LLM). Retorno: {ok, comando, resposta(markdown)}."""
    try:
        from compliance_agent.nucleo import telegram_nucleo as tn

        p = payload or {}
        comando = str(p.get("comando") or "").strip().lower()
        args = str(p.get("args") or "").strip()
        if not comando:
            interp = tn.interpretar_texto_livre(str(p.get("texto") or "").strip())
            if not interp:
                return JSONResponse(content={"ok": False, "erro": "pedido não reconhecido pelo roteador "
                                             "determinístico — use {comando, args} explícito"}, status_code=422)
            comando, args = interp
        handlers = {"/pericia": lambda: tn.cmd_pericia(args), "/veredito": lambda: tn.cmd_veredito(args),
                    "/fantasma": lambda: tn.cmd_fantasma(args), "/fases": lambda: tn.cmd_fases(args),
                    "/certame": lambda: tn.cmd_certame(args),
                    "/promover": lambda: tn.cmd_promover(args), "/placar": tn.cmd_placar,
                    "/ciclo_nucleo": tn.cmd_ciclo_nucleo, "/fornecedor": lambda: tn.cmd_fornecedor(args),
                    "/parametros": tn.cmd_parametros, "/evolucao": tn.cmd_evolucao}
        fn = handlers.get(comando)
        if fn is None:
            return JSONResponse(content={"ok": False, "erro": f"comando desconhecido: {comando}",
                                         "comandos": sorted(handlers)}, status_code=422)
        resposta = await asyncio.to_thread(fn)
        return JSONResponse(content={"ok": True, "comando": comando, "args": args, "resposta": resposta})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)
