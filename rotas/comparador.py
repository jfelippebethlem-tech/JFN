# -*- coding: utf-8 -*-
"""Comparador de preços (`/api/comparador/*`) e o sobrepreço por código CATMAT/CATSER (`/api/sobrepreco`).

Saiu de `rotas/investigacao.py` na O7.6 (2026-11-25), sem mudar comportamento: mesmas rotas, mesmos corpos.
O cache do painel e os ajudantes (`_ro`, `_cache_calc`…) continuam em `rotas/investigacao.py` e são importados de lá
(o materializador e os testes redirecionam aqueles nomes naquele módulo)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from rotas.investigacao import _cache_calc, _cache_get, _cache_put

router = APIRouter()


@router.get("/api/sobrepreco")
async def api_sobrepreco(codigo: int, valor: float = 0, servico: bool = False):
    """Onda 3 (R4) — Sobrepreço: preço pago vs mediana de referência de mercado.

    codigo = CATMAT (material) ou CATSER (servico=true). valor = preço pago a comparar.
    Fonte: Compras Dados Abertos. Honesto: sem amostra => mediana_ref=null/INDISPONÍVEL;
    o % é indício a verificar (especificação/quantidade/região podem justificar), nunca acusação.
    """
    try:
        from compliance_agent.sobrepreco import sobrepreco

        res = await sobrepreco(codigo, valor_pago=(valor or None), servico=servico)
        return JSONResponse(content=res)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/comparador/buscar")
def api_comparador_buscar(termo: str = "", esfera: str = ""):
    """Grupos de item que casam o termo (ex.: 'aluguel carro', 'medicamento'), com dispersão de
    preço entre órgãos — abrir um grupo mostra quem paga mais/menos."""
    try:
        from compliance_agent.comparador_precos import buscar_grupos
        t = (termo or "").strip()[:60]
        if len(t) < 3:
            return JSONResponse({"ok": False, "erro": "termo muito curto (≥3 letras)"})
        ck = f"comp:busca:{t.lower()}:{esfera or 'todas'}"
        d = _cache_calc(ck, 600, lambda: buscar_grupos(t, esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/catalogo")
async def api_comparador_catalogo(esfera: str = ""):
    """Catálogo navegável: TODOS os grupos comparáveis por CATEGORIA (menu→submenu→item).
    Filtros/ordenação são do cliente; aqui só a estrutura, cacheada."""
    try:
        from compliance_agent.comparador_precos import catalogo
        ck = f"comp:catalogo:{esfera or 'todas'}"
        if not (d := _cache_get(ck, 1800)):
            d = _cache_put(ck, await asyncio.to_thread(catalogo, esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/item")
def api_comparador_item(grupo: str = "", unidade: str = "", esfera: str = ""):
    """Para um item (grupo normalizado), ranking de ÓRGÃOS e FORNECEDORES por preço unitário."""
    try:
        from compliance_agent.comparador_precos import comparar
        g = (grupo or "").strip()
        if not g:
            return JSONResponse({"ok": False, "erro": "grupo vazio"})
        ck = f"comp:item:{g}:{(unidade or '').lower()}:{esfera or 'todas'}"
        d = _cache_calc(ck, 600, lambda: comparar(g, unidade or None, esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/economia")
def api_comparador_economia(esfera: str = ""):
    """Economia potencial: quanto os cofres economizariam se cada compra acima da mediana tivesse
    pago a mediana de mercado do item. Total + quebra por item/órgão/fornecedor."""
    try:
        from compliance_agent.comparador_precos import economia_potencial
        ck = f"comp:economia:{esfera or 'todas'}"
        d = _cache_calc(ck, 1800, lambda: economia_potencial(esfera=esfera or None))
        from compliance_agent.proveniencia_manchetes import anexar
        return JSONResponse(anexar("/api/comparador/economia", d))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/vedada")
def api_comparador_vedada(esfera: str = ""):
    """O número mais forte: sobrepreço (acima da mediana) pago a fornecedor JURIDICAMENTE VEDADO
    de contratar com aquele ente comprador, VIGENTE à época. Inidoneidade veda todos."""
    try:
        from compliance_agent.comparador_precos import economia_vedada
        ck = f"comp:vedada:{esfera or 'todas'}"
        d = _cache_calc(ck, 1800, lambda: economia_vedada(esfera=esfera or None))
        from compliance_agent.proveniencia_manchetes import anexar
        return JSONResponse(anexar("/api/comparador/vedada", d))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/dossie")
def api_comparador_dossie(esfera: str = ""):
    """Dossiê automático: item pago muito acima da mediana por um órgão cujo FORNECEDOR já é
    sancionado/no radar/fantasma. Cruza o comparador de preços com o gabarito de risco."""
    try:
        from compliance_agent.comparador_precos import caro_e_suspeito
        ck = f"comp:dossie:{esfera or 'todas'}"
        d = _cache_calc(ck, 1800, lambda: caro_e_suspeito(esfera=esfera or None))
        from compliance_agent.proveniencia_manchetes import anexar
        return JSONResponse(anexar("/api/comparador/dossie", d))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/orgaos")
def api_comparador_orgaos(esfera: str = ""):
    """Ranking de órgãos por eficiência de gasto (razão preço/mercado ao longo de muitos itens)."""
    try:
        from compliance_agent.comparador_precos import ranking_orgaos
        ck = f"comp:orgaos:{esfera or 'todas'}"
        d = _cache_calc(ck, 1800, lambda: ranking_orgaos(esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/comparador/fornecedores")
def api_comparador_fornecedores(esfera: str = ""):
    """Ranking de fornecedores por preço relativo (mais caros / mais baratos vs mercado)."""
    try:
        from compliance_agent.comparador_precos import ranking_fornecedores
        ck = f"comp:forn:{esfera or 'todas'}"
        d = _cache_calc(ck, 1800, lambda: ranking_fornecedores(esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)
