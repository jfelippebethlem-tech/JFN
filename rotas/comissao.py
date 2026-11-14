# -*- coding: utf-8 -*-
"""Rotas da sub-aba "Comissão de Orçamento" (ALERJ) — Estado › Comissão de Orçamento."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/comissao/orgaos")
def api_comissao_orgaos(limite: int = 40, orgao: str = ""):
    """Órgão a órgão (ALERJ, TCE-RJ, TJRJ, MPRJ, DPRJ primeiro; depois o Executivo): fornecedores com problema
    — perícia 🔴/🟡 com cada indício e a evidência, situação da duplicidade por competência e achados confirmados
    dos detectores. Indício não é acusação; valor = OB Contabilizado do SIAFE."""
    from compliance_agent.comissao_orcamento import montar
    try:
        return JSONResponse(montar(max(5, min(int(limite or 40), 1000)), orgao=(orgao or "").strip()[:2]))
    except (sqlite3.Error, OSError, ValueError, KeyError) as exc:   # a tela mostra o erro em vez de travar
        return JSONResponse({"ok": False, "erro": f"{type(exc).__name__}: {exc}"}, status_code=500)


@router.get("/api/comissao/pecas")
def api_comissao_pecas():
    """Catálogo das 18 peças da Comissão (base legal, prazo), última versão gerada de cada uma e o calendário."""
    from compliance_agent.comissao_pecas import CALENDARIO, CATALOGO, ultimas_geradas
    ult = ultimas_geradas()
    pecas = [{**{k: p.get(k) for k in ("id", "titulo", "base", "prazo", "falta")}, "gerar": bool(p.get("gerador")),
              "url": f"/reports/{ult[p['id']]}" if p["id"] in ult else None} for p in CATALOGO]
    return JSONResponse({"ok": True, "pecas": pecas,
                         "calendario": [{"quando": q, "evento": e, "pecas": pc} for q, e, pc in CALENDARIO]})


@router.get("/api/comissao/pecas/gerar")
def api_comissao_pecas_gerar(id: str):  # noqa: A002 — nome do parâmetro é o da URL
    """Gera agora a peça `id` (PDF no padrão da casa) e devolve a URL."""
    from compliance_agent.comissao_pecas import gerar
    try:
        pdf = gerar((id or "").strip().upper())
    except (sqlite3.Error, OSError, ValueError, KeyError) as exc:
        return JSONResponse({"ok": False, "erro": f"{type(exc).__name__}: {exc}"}, status_code=500)
    if not pdf:
        return JSONResponse({"ok": False, "erro": "peça sem gerador ou sem dado na base"}, status_code=404)
    return JSONResponse({"ok": True, "url": f"/reports/{pdf.name}"})


@router.get("/api/comissao/pulos")
def api_comissao_pulos(ano: int = 0, mes: int = 0):
    """Detectores dos "pulos do gato" do orçamento (suplementação por decreto, DEA recorrente, restos a pagar, art. 42,
    troca de fonte, reserva de contingência, empenho em dezembro, ordem cronológica, mínimos), com o texto do manual
    ao lado, prevalência medida, estado VERIFICADO/PENDENTE de cada número e filtro por ano e mês. Lê o arquivo
    gerado por `tools/pulos_do_gato_semanal.py`; indício não é acusação e empenho nunca é chamado de pago."""
    from compliance_agent.pulos_do_gato import filtrar, ler
    try:
        painel = ler()
    except (OSError, ValueError) as exc:
        return JSONResponse({"ok": False, "erro": f"{type(exc).__name__}: {exc}"}, status_code=500)
    if not painel:
        return JSONResponse({"ok": False, "erro": "detectores ainda não rodaram (tools/pulos_do_gato_semanal.py)"},
                            status_code=404)
    return JSONResponse(filtrar(painel, ano=ano or None, mes=mes if 1 <= mes <= 12 else None))
