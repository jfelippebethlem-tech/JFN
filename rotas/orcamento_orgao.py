# -*- coding: utf-8 -*-
"""Rota da sub-aba "Orçamento por órgão" — Estado › Orçamento por órgão (pedido do dono, 14/11/2026)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/orcamento_orgao")
def api_orcamento_orgao(ano: int = 0, mes: int = 0):
    """Por órgão (com unidade orçamentária e UG), no exercício `ano` e acumulado até `mes`: dotação inicial e
    atualizada, empenhado, liquidado, pago por OB Contabilizada do SIAFE, pago do balancete (referência), a
    diferença entre os dois e as taxas de execução, com ranking. Cada coluna declara fonte e estado; o que a fonte
    não tem vem INDISPONÍVEL (nunca zero, nunca estimado). Só leitura. A base de cada exercício passa pelo cache
    do painel (1 h, persistido em disco); o recorte por mês é montado em cima dela a cada chamada."""
    from compliance_agent import orcamento_orgao as O
    from rotas.investigacao import _cache_calc
    try:
        exs = _cache_calc(f"orcamento_orgao:v{O.VERSAO}:exercicios", 3600, O.exercicios)
        alvo = ano or O.exercicio_padrao(exs)
        if alvo not in {e["ano"] for e in exs}:
            return JSONResponse({"ok": False, "erro": f"exercício {alvo} não está na base", "exercicios": exs},
                                status_code=404)
        base = _cache_calc(f"orcamento_orgao:v{O.VERSAO}:base:{alvo}", 3600, lambda: O.carregar(alvo))
        return JSONResponse(O.montar(base, mes if 1 <= mes <= 12 else None, exs))
    except (sqlite3.Error, OSError, ValueError, KeyError) as exc:   # a tela mostra o erro em vez de travar
        return JSONResponse({"ok": False, "erro": f"{type(exc).__name__}: {exc}"}, status_code=500)
