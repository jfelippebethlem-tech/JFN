# -*- coding: utf-8 -*-
"""Rota do estado da PROPAGAÇÃO AUTOMÁTICA — Sistema › Propagação.

  /api/sistema/propagacao — o que ficou sujo, o que foi recalculado e quando, o que falhou, e o que seguiu para o
                            segundo cérebro (compliance_agent/propagacao.py::estado)

  /api/sistema/certeza    — painel de CERTEZA: por fato (id), valor, estado, nível de prova, confiança, proveniência,
                            frescor e divergências abertas; contratos de dados; auditoria do grafo
                            (compliance_agent/certeza/orquestrador.py::ler_estado — a fotografia do último ciclo)

Só leitura e leve: lê `data/propagacao.db` (base própria do despachante, que roda pelo cron FORA deste processo) e
`config/propagacao.yaml`. Não dispara recálculo. Base ausente ou ilegível = INDISPONÍVEL (≠ "nada sujo").
Custo de API e uso da assinatura não entram aqui (dono, 14/11/2026).
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from yaml import YAMLError

router = APIRouter()


@router.get("/api/sistema/propagacao")
def api_sistema_propagacao():
    """Estado da propagação: derivados (sujo, último recálculo, falha), fontes, eventos, execuções e cérebro."""
    from compliance_agent import propagacao
    try:
        return JSONResponse(propagacao.estado())
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, YAMLError) as exc:
        return JSONResponse({"ok": False, "estado": "INDISPONIVEL",
                             "motivo": f"falha ao ler o estado da propagação — {type(exc).__name__}: {exc}"})


@router.get("/api/sistema/certeza")
def api_sistema_certeza(fato: str | None = None):
    """Painel de certeza (docs/ARQUITETURA-DE-CERTEZA.md). `?fato=<trecho do id>` devolve só os fatos que casam.
    Sem ciclo gravado = INDISPONÍVEL (≠ "sem divergência")."""
    from compliance_agent.certeza import orquestrador
    est = orquestrador.ler_estado()
    if fato and est.get("ok"):
        est = {**est, "fatos": [f for f in est["fatos"] if fato in f["id"]],
               "divergencias": [d for d in est["divergencias"] if fato in d["fato_id"]]}
    return JSONResponse(est)
