# -*- coding: utf-8 -*-
"""Rotas da LAI automatizada: gerar requerimento, listar, mudar status, prazos vencendo."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _links(r: dict) -> dict:
    """Caminhos em reports/ viram URLs servidas por /reports/{filename}."""
    for k in ("path_docx", "path_md"):
        p = r.get(k)
        if p:
            r[k.replace("path_", "url_")] = f"/reports/{Path(p).name}"
    return r


@router.post("/api/lai/gerar")
async def api_lai_gerar(payload: Optional[dict] = None):
    """Body {"alvo": "SME-PRO-2025/38233" | "2509437" | CNPJ | nome, "esfera": opcional, "motivo": opcional,
    "telegram": 0|1}. Devolve o requerimento pronto (texto + .docx/.md) e o registro com id."""
    p = payload or {}
    try:
        from compliance_agent.lai import gerar
        r = await asyncio.to_thread(gerar, p.get("alvo", ""), p.get("esfera") or None, p.get("motivo") or None)
        if not r.get("ok"):
            return JSONResponse(content=r, status_code=400)
        r = _links(r)
        if p.get("telegram"):
            try:
                from rotas.produtos import _enviar_docs_telegram
                asyncio.create_task(_enviar_docs_telegram(r, f"Requerimento LAI #{r['id']} — {r['alvo']}"))
            except Exception as exc:  # noqa: BLE001 — entrega é acessória
                logger.warning("LAI: envio Telegram falhou: %s", exc)
        r.pop("texto_docx", None)
        return JSONResponse(content=r)
    except Exception as e:  # noqa: BLE001
        logger.exception("LAI gerar falhou")
        return JSONResponse(content={"ok": False, "erro": str(e)[:300]}, status_code=500)


@router.get("/api/lai/lista")
async def api_lai_lista(limite: int = 100):
    from compliance_agent.lai import listar
    itens = [_links(d) for d in listar(limite)]
    return JSONResponse(content={"ok": True, "n": len(itens), "itens": itens})


@router.post("/api/lai/status")
async def api_lai_status(payload: Optional[dict] = None):
    """Body {"id", "status": rascunho|protocolado|respondido|negado|recurso|arquivado, "protocolo"?, "notas"?}."""
    p = payload or {}
    try:
        from compliance_agent.lai import atualizar
        r = atualizar(int(p.get("id")), p.get("status", ""), p.get("protocolo"), p.get("notas"))
        return JSONResponse(content={"ok": True, "item": _links(r)})
    except (ValueError, TypeError) as e:
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=400)


@router.get("/api/lai/prazos")
async def api_lai_prazos(dias: int = 3):
    from compliance_agent.lai import vencendo
    itens = vencendo(dias)
    return JSONResponse(content={"ok": True, "n": len(itens), "itens": itens})
