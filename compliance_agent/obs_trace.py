# -*- coding: utf-8 -*-
"""
obs_trace — observabilidade do JFN (JFN 2.0, Onda 0).

Injeta um correlation_id (uuid4) por request HTTP, devolve no header X-Correlation-Id, loga uma linha JSON
por request em logs/trace/AAAAMMDD.jsonl, e expõe GET /api/trace/{correlation_id} que devolve as etapas
registradas daquele id. Tudo ADITIVO e best-effort (nunca derruba o request se o log falhar).

Integração mínima no server.py:
    from compliance_agent.obs_trace import register_trace
    register_trace(app)          # logo após `app = FastAPI(...)`

Para anotar etapas internas a partir de qualquer handler:
    from compliance_agent.obs_trace import trace_evento
    trace_evento(request, "siafe.coleta.inicio", {"ug": ug})
"""
from __future__ import annotations

import logging
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TRACE_DIR = _REPO / "logs" / "trace"


logger = logging.getLogger(__name__)


def _arquivo_do_dia() -> Path:
    _TRACE_DIR.mkdir(parents=True, exist_ok=True)
    return _TRACE_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"


def _append(registro: dict) -> None:
    """Grava 1 linha JSON (best-effort; engole erro p/ nunca quebrar o request)."""
    try:
        with open(_arquivo_do_dia(), "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("trace não gravado: %s", exc)


def trace_evento(request, etapa: str, dados: dict | None = None) -> None:
    """Registra uma etapa intermediária ligada ao correlation_id do request atual."""
    cid = getattr(getattr(request, "state", None), "correlation_id", None)
    if not cid:
        return
    _append({"correlation_id": cid, "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
             "tipo": "etapa", "etapa": etapa, "dados": dados or {}})


def etapas_de(correlation_id: str, max_dias: int = 3) -> list[dict]:
    """Lê os jsonl recentes e devolve as linhas do correlation_id (ordem cronológica)."""
    out: list[dict] = []
    if not _TRACE_DIR.exists():
        return out
    arquivos = sorted(_TRACE_DIR.glob("*.jsonl"), reverse=True)[:max_dias]
    for arq in arquivos:
        try:
            for linha in arq.read_text(encoding="utf-8").splitlines():
                if correlation_id in linha:
                    try:
                        r = json.loads(linha)
                    except Exception:
                        continue
                    if r.get("correlation_id") == correlation_id:
                        out.append(r)
        except Exception:
            continue
    return sorted(out, key=lambda r: r.get("ts", ""))


def register_trace(app) -> None:
    """Adiciona o middleware de correlation-id e a rota GET /api/trace/{correlation_id} ao app FastAPI."""
    from starlette.responses import JSONResponse

    @app.middleware("http")
    async def _correlation_mw(request, call_next):  # noqa: ANN001
        cid = request.headers.get("X-Correlation-Id") or uuid.uuid4().hex
        try:
            request.state.correlation_id = cid
        except Exception as exc:
            logger.debug("correlation_id não anexado ao request: %s", exc)
        t0 = time.time()
        status = 500
        try:
            resp = await call_next(request)
            status = resp.status_code
            resp.headers["X-Correlation-Id"] = cid
            return resp
        finally:
            _append({"correlation_id": cid, "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                     "tipo": "request", "metodo": request.method, "rota": request.url.path,
                     "status": status, "duracao_ms": round((time.time() - t0) * 1000, 1)})

    @app.get("/api/trace/{correlation_id}")
    async def _get_trace(correlation_id: str):  # noqa: ANN001
        etapas = etapas_de(correlation_id)
        return JSONResponse({"correlation_id": correlation_id, "encontrado": bool(etapas), "etapas": etapas})
