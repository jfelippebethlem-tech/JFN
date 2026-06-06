"""
Coletor de contratos públicos do Portal Nacional de Contratações Públicas (PNCP).

Fonte: https://pncp.gov.br/api/consulta/v1/contratos
Sem autenticação — API pública.
"""
from __future__ import annotations

import asyncio
import os
import re
import logging
import time
from datetime import date
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_PNCP_URL = "https://pncp.gov.br/api/consulta/v1/contratos"
_TIMEOUT = 18  # apertado p/ não estourar o cap de 35s do relatório (o terminal do Yoda mata em 60s)
_BUDGET = float(os.environ.get("JFN_PNCP_BUDGET", "25"))  # orçamento total (s) p/ varrer todos os anos
# PNCP começou em 2021 e EXIGE janela dataInicial/dataFinal (≤ 1 ano por consulta) — varremos ano a ano.
_ANO_INICIO = int(os.environ.get("JFN_PNCP_ANO_INICIO", "2021"))


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
    tam: int = 50,
    todas_paginas: bool = True,
    anos: Optional[list[int]] = None,
) -> dict:
    """
    Busca contratos públicos vinculados ao CNPJ fornecedor no PNCP.

    A API `/v1/contratos` EXIGE `dataInicial`/`dataFinal` (YYYYMMDD, janela ≤ 1 ano) — sem isso responde
    **HTTP 400**. Por isso varremos **ano a ano** (de `anos`, ou de _ANO_INICIO até o ano corrente) e
    deduplicamos por `id_pncp`. Respeita um orçamento total (_BUDGET) para não estourar o cap do relatório.

    Parâmetros
    ----------
    cnpj         : CNPJ do fornecedor (com ou sem pontuação)
    pagina       : página inicial (começa em 1)
    tam          : tamanho da página (mín. 10, máx. 500 na API)
    todas_paginas: se True, percorre todas as páginas de cada ano
    anos         : lista de exercícios a varrer (default: _ANO_INICIO..ano corrente)

    Retorno
    -------
    dict com "ok", "total", "contratos" (lista normalizada, deduplicada)
    """
    cnpj_limpo = _limpar_cnpj(cnpj)
    if len(cnpj_limpo) != 14:
        return {"ok": False, "erro": f"CNPJ inválido: {cnpj!r}", "total": 0, "contratos": []}

    if not anos:
        anos = list(range(_ANO_INICIO, date.today().year + 1))
    tam = max(10, tam)  # a API rejeita tamanhoPagina < 10
    t0 = time.monotonic()

    async def _buscar_pagina(client: httpx.AsyncClient, ano: int, pag: int) -> tuple[int, list]:
        p = {"cnpjFornecedor": cnpj_limpo, "dataInicial": f"{ano}0101", "dataFinal": f"{ano}1231",
             "pagina": pag, "tamanhoPagina": tam}
        r = await client.get(_PNCP_URL, params=p, timeout=_TIMEOUT)
        if r.status_code in (204, 404):  # sem conteúdo
            return 0, []
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        data = r.json()
        if isinstance(data, list):
            return len(data), data
        itens = data.get("data") or data.get("contratos") or data.get("content") or []
        total = int(data.get("totalRegistros") or data.get("total")
                    or data.get("totalElements") or len(itens))
        return total, itens

    todos_itens: list[dict] = []
    parcial = False
    try:
        async with httpx.AsyncClient() as client:
            for ano in anos:
                if time.monotonic() - t0 > _BUDGET:
                    parcial = True
                    logger.warning("PNCP: orçamento esgotado, varredura parcial (parou em %s)", ano)
                    break
                try:
                    total, primeira = await _buscar_pagina(client, ano, pagina)
                except (httpx.TimeoutException, RuntimeError) as exc:
                    logger.warning("PNCP ano %s falhou: %s", ano, exc)
                    parcial = True
                    continue
                todos_itens.extend(primeira)
                if todas_paginas and total > tam:
                    import math
                    n_paginas = math.ceil(total / tam)
                    for inicio in range(pagina + 1, n_paginas + 1, 10):
                        if time.monotonic() - t0 > _BUDGET:
                            parcial = True
                            break
                        fim = min(inicio + 10, n_paginas + 1)
                        resultados = await asyncio.gather(
                            *[_buscar_pagina(client, ano, p) for p in range(inicio, fim)],
                            return_exceptions=True,
                        )
                        for res in resultados:
                            if isinstance(res, Exception):
                                logger.warning("Erro em página PNCP: %s", res)
                                parcial = True
                                continue
                            _, itens = res
                            todos_itens.extend(itens)

        # normaliza + deduplica por id_pncp (o mesmo contrato pode reaparecer entre janelas)
        vistos: set[str] = set()
        contratos: list[dict] = []
        for c in (_normalizar_contrato(x) for x in todos_itens):
            chave = c["id_pncp"] or f"{c['numero_contrato']}|{c['cnpj_orgao']}|{c['objeto'][:40]}"
            if chave in vistos:
                continue
            vistos.add(chave)
            contratos.append(c)

        return {
            "ok": True,
            "cnpj": cnpj_limpo,
            "total": len(contratos),
            "total_obtidos": len(contratos),
            "paginas_completas": todas_paginas and not parcial,
            "parcial": parcial,
            "contratos": contratos,
        }

    except httpx.TimeoutException:
        return {"ok": False, "erro": "Timeout ao consultar PNCP", "total": 0, "contratos": [], "cnpj": cnpj_limpo}
    except Exception as exc:
        logger.exception("Erro ao consultar PNCP para CNPJ %s", cnpj_limpo)
        return {"ok": False, "erro": str(exc), "total": 0, "contratos": [], "cnpj": cnpj_limpo}
