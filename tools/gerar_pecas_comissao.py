#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera todas as peças automáticas da Comissão de Orçamento (P10–P13) — cron semanal, após o coletor do SICONFI.

    PYTHONPATH=. .venv/bin/python tools/gerar_pecas_comissao.py
"""
import json
import sqlite3
import sys

from compliance_agent.comissao_pecas import CATALOGO, gerar

if __name__ == "__main__":
    res = {}
    for p in CATALOGO:
        if not p.get("gerador"):
            continue
        try:
            pdf = gerar(p["id"])
            res[p["id"]] = pdf.name if pdf else "sem dado"
        except (sqlite3.Error, OSError, ValueError, KeyError) as e:
            res[p["id"]] = f"ERRO {type(e).__name__}: {e}"[:160]
    print(json.dumps(res, ensure_ascii=False))
    sys.exit(1 if any(str(v).startswith("ERRO") for v in res.values()) else 0)
