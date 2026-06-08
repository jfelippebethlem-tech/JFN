# -*- coding: utf-8 -*-
"""Testes da Onda 0 do JFN 2.0: capabilities.yaml válido + observabilidade (correlation-id + /api/trace)."""
from __future__ import annotations


def test_capabilities_valido():
    """O contrato único capabilities.yaml passa no validador (schema + rotas PRONTO existem)."""
    from tools.validate_capabilities import validar
    erros = validar()
    assert erros == [], f"capabilities.yaml inválido: {erros}"


def test_obs_trace_header_e_rota():
    """Qualquer request recebe X-Correlation-Id e GET /api/trace/{id} mostra as etapas (aceite Onda 0b)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from compliance_agent.obs_trace import register_trace

    app = FastAPI()
    register_trace(app)

    @app.get("/ping")
    def _ping():
        return {"ok": True}

    cli = TestClient(app)
    r = cli.get("/ping")
    cid = r.headers.get("x-correlation-id")
    assert cid, "header X-Correlation-Id ausente"
    tr = cli.get(f"/api/trace/{cid}").json()
    assert tr["encontrado"] is True
    assert any(e.get("rota") == "/ping" for e in tr["etapas"])
