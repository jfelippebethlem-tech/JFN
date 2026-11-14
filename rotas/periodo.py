# -*- coding: utf-8 -*-
"""Rotas da organização por ANO e MÊS — o seletor Ano/Mês e o bloco "Por ano e mês" do painel.

``GET /api/periodo/{fonte}?ano=&mes=`` — sem filtro = a quebra completa (comportamento de sempre das abas);
com filtro = a MESMA quebra mais o recorte pedido e os maiores registros do período. A quebra inteira de uma
fonte é UM cálculo em cache (1 h, single-flight, SWR, disco — o mesmo cache do painel, mantido quente pelo
``tools/prewarm_painel.sh``): trocar de ano/mês recorta o que já está calculado, não reconta a base. Só os
"maiores do período" são consulta própria, também em cache por (fonte, ano, mês).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()
RAIZ = Path(__file__).resolve().parent.parent
_TTL = 3600


def _con():
    db = Path(os.environ.get("JFN_DATA_DIR", RAIZ / "data")) / "compliance.db"
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)


def _calc(fid: str):
    from compliance_agent import periodo_fontes as F

    def calcular():
        con = _con()
        try:
            return F.calcular(con, fid, date.today())
        finally:
            con.close()
    return calcular


def _itens(fid: str, ano: int, mes: int | None):
    from compliance_agent import periodo_fontes as F

    def calcular():
        con = _con()
        try:
            return F.FONTES[fid].itens(con, ano, mes)
        finally:
            con.close()
    return calcular


@router.get("/api/periodo/fontes")
def api_periodo_fontes():
    """As fontes datadas que o seletor Ano/Mês conhece, com esfera, campo de data e medidas."""
    from compliance_agent import periodo_fontes as F
    return JSONResponse({"ok": True, "fontes": [F.meta(f) for f in F.FONTES.values()]})


@router.get("/api/periodo/{fonte}")
def api_periodo(fonte: str, ano: str = "", mes: str = ""):
    """Quebra ano → mês de UMA fonte (Estado e Prefeitura são fontes distintas), com cobertura declarada.
    ``ano``/``mes`` inválidos → 400 com o motivo (nunca lista vazia)."""
    from compliance_agent import periodo as P
    from compliance_agent import periodo_fontes as F
    from rotas.investigacao import _cache_calc
    if fonte not in F.FONTES:
        return JSONResponse({"ok": False, "erro": f"fonte '{fonte}' não existe — use uma de {list(F.FONTES)}"},
                            status_code=404)
    try:
        a, m = P.validar(ano, mes)
    except P.PeriodoInvalido as exc:
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=400)
    try:
        d = _cache_calc(f"periodo:{fonte}:v1", _TTL, _calc(fonte))
        P.conferir(d["quebra"])                  # o que sai do cache em disco também tem de fechar
        sel = P.selecao(d["quebra"], a, m)
        itens = None
        if a is not None and sel.get("status") != P.INDISPONIVEL:
            itens = _cache_calc(f"periodo:{fonte}:itens:{a}:{m or 0}:v1", _TTL, _itens(fonte, a, m))
        return JSONResponse({"ok": True, **d, "filtro": {"ano": a, "mes": m, "rotulo": P.rotulo(a, m)},
                             "selecao": sel, "itens": itens, "top": F.TOP})
    except (sqlite3.Error, OSError, P.SomaNaoFecha) as exc:   # a tela diz INDISPONÍVEL com o motivo
        return JSONResponse({"ok": False, "erro": f"{type(exc).__name__}: {exc}"}, status_code=500)
