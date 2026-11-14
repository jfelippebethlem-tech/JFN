# -*- coding: utf-8 -*-
"""Rota do PAINEL DE CONFORMIDADE — Transversal › Conformidade.

  /api/qualidade/conformidade — por sistema: regras de qualidade que valem, violações abertas, tendência, juiz
                                subjetivo e dívida (compliance_agent/qualidade/estado.py::painel)

Só leitura e leve: `estado.painel()` só LÊ o que sensores, juiz e catracas já gravaram — não dispara sensor nem
modelo. Sem fotografia dos sensores o estado é INDISPONIVEL (≠ zero); falha de leitura idem, nunca "0 violações".
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from yaml import YAMLError

router = APIRouter()


@router.get("/api/qualidade/conformidade")
def api_qualidade_conformidade():
    """Estado das regras de qualidade por sistema: regras, violações abertas, bloqueantes, tendência, juiz, dívida."""
    from compliance_agent.qualidade import estado
    try:
        return JSONResponse(estado.painel())
    except (OSError, ValueError, KeyError, TypeError, YAMLError) as exc:   # registro ilegível ≠ zero violações
        return JSONResponse({"ok": False, "estado": "INDISPONIVEL",
                             "motivo": f"falha ao ler o estado de qualidade — {type(exc).__name__}: {exc}"})
