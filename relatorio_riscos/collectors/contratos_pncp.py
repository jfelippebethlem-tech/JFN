"""
Coletor de contratos públicos do Portal Nacional de Contratações Públicas (PNCP).

Fonte: https://pncp.gov.br/api/consulta/v1/contratos
Sem autenticação — API pública.
"""
from __future__ import annotations

import re
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_PNCP_URL = "https://pncp.gov.br/api/consulta/v1/contratos"
_TIMEOUT = 30


def _limpar_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj)


def _safe_float(valor) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalizar_contrato(c: dict) -> dict:
    return {
        "id_pncp": c.get("numeroControlePNCP") or c.get("id") or "",
        "orgao": c.get("orgaoEntidade", {}).get("razaoSocial") or c.get("unidadeOrgao", {}).get("nomeUnidade") or "",
        "cnpj_orgao": c.get("orgaoEntidade", {}).get("cnpj") or "",
        "objeto": c.get("objetoContrato") or c.get("objeto") or "",
        "modalidade": c.get("modalidadeNome") or c.get("modalidade") or "",
        "valor_global": _safe_float(c.get("valorGlobal") or c.get("valorTotal")),
        "data_assinatura": c.get("dataAssinatura") or c.get("dataInicioVigencia") or "",
        "vigencia_inicio": c.get("dataInicioVigencia") or "",
        "vigencia_fim": c.get("dataFimVigencia") or "",
        "numero_contrato": c.get("numeroContratoEmpenho") or c.get("numeroContrato") or "",
    }


async def buscar_contratos_por_cnpj(
    cnpj: str,
    pagina: int = 1,
    tam: int = 20,
) -> dict:
    """
    Busca contratos públicos vinculados ao CNPJ fornecedor no PNCP.

    Parâmetros
    ----------
    cnpj   : CNPJ do fornecedor (com ou sem pontuação)
    pagina : página da consulta (começa em 1)
    tam    : tamanho da página (máx. 500 na API)

    Retorno
    -------
    dict com "ok", "total", "contratos" (lista normalizada)
    """
    cnpj_limpo = _limpar_cnpj(cnpj)
    if len(cnpj_limpo) != 14:
        return {"ok": False, "erro": f"CNPJ inválido: {cnpj!r}", "total": 0, "contratos": []}

    params = {
        "cnpjFornecedor": cnpj_limpo,
        "pagina": pagina,
        "tamanhoPagina": tam,
    }

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(_PNCP_URL, params=params, timeout=_TIMEOUT)

        if r.status_code == 404:
            # PNCP retorna 404 quando não encontra contratos
            return {"ok": True, "total": 0, "contratos": [], "cnpj": cnpj_limpo}

        if r.status_code != 200:
            return {
                "ok": False,
                "erro": f"PNCP retornou HTTP {r.status_code}",
                "total": 0,
                "contratos": [],
                "cnpj": cnpj_limpo,
            }

        data = r.json()

        # A API pode retornar lista direta ou objeto paginado
        if isinstance(data, list):
            itens = data
            total = len(itens)
        elif isinstance(data, dict):
            itens = data.get("data") or data.get("contratos") or data.get("content") or []
            total = (
                data.get("totalRegistros")
                or data.get("total")
                or data.get("totalElements")
                or len(itens)
            )
            total = int(total)
        else:
            itens = []
            total = 0

        contratos = [_normalizar_contrato(c) for c in itens]

        return {
            "ok": True,
            "cnpj": cnpj_limpo,
            "total": total,
            "pagina": pagina,
            "tam_pagina": tam,
            "contratos": contratos,
        }

    except httpx.TimeoutException:
        return {
            "ok": False,
            "erro": "Timeout ao consultar PNCP",
            "total": 0,
            "contratos": [],
            "cnpj": cnpj_limpo,
        }
    except Exception as exc:
        logger.exception("Erro ao consultar PNCP para CNPJ %s", cnpj_limpo)
        return {
            "ok": False,
            "erro": str(exc),
            "total": 0,
            "contratos": [],
            "cnpj": cnpj_limpo,
        }
