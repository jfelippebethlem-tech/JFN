# -*- coding: utf-8 -*-
"""Rota do estado da PROPAGAÇÃO AUTOMÁTICA — Sistema › Propagação.

  /api/sistema/propagacao — o que ficou sujo, o que foi recalculado e quando, o que falhou, e o que seguiu para o
                            segundo cérebro (compliance_agent/propagacao.py::estado)

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
