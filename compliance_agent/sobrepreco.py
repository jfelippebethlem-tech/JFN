# -*- coding: utf-8 -*-
"""Sobrepreço (R4) — JFN 2.0, Onda 3. Preço pago vs mediana de referência de mercado.

Fonte: Compras Dados Abertos (módulo pesquisa de preço, por CATMAT/CATSER) — substitui o
Painel de Preços (descontinuado em 04/07/2025). API pública, sem login.

Honestidade (invariante): se NÃO houver amostra de referência, retorna mediana_ref=None e
fonte='INDISPONÍVEL' — NUNCA fabrica preço. O percentual é INDÍCIO de sobrepreço a
verificar (pode haver diferença de especificação/quantidade/região), nunca acusação.
"""
from __future__ import annotations

import statistics
from typing import Optional

import httpx

_BASE = "https://dadosabertos.compras.gov.br/modulo-pesquisa-preco"
_EP_MATERIAL = "/1_consultarMaterial"
_EP_SERVICO = "/2_consultarServico"


async def _coletar_precos(codigo: int, servico: bool, max_paginas: int) -> list[float]:
    ep = _EP_SERVICO if servico else _EP_MATERIAL
    precos: list[float] = []
    async with httpx.AsyncClient(timeout=40) as client:
        for pagina in range(1, max_paginas + 1):
            params = {"pagina": pagina, "tamanhoPagina": 100, "codigoItemCatalogo": codigo}
            try:
                r = await client.get(f"{_BASE}{ep}", params=params,
                                     headers={"User-Agent": "JFN-Compliance/2.0"})
                if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
                    break
                res = (r.json() or {}).get("resultado") or []
            except Exception:
                break
            if not res:
                break
            for it in res:
                p = it.get("precoUnitario")
                if isinstance(p, (int, float)) and p > 0:
                    precos.append(float(p))
            if len(res) < 100:
                break
    return precos


# Calibração (honestidade — indício≠acusação): NÃO se aponta sobrepreço sem base estatística.
_MIN_AMOSTRA = 5      # abaixo disso a "mediana" é ruído (1-4 preços) → referência fraca, sem indício
_IQR_DISPERSAO = 3.0  # p75/p25 ≥ 3 ⇒ referência heterogênea (especificação/região) → desvio pode ser ruído


def _classificar(pct: float, n_amostra: int = 999, iqr_ratio: float | None = None) -> str:
    """Faixa do indício de sobrepreço (sobre o desvio % vs mediana), com guardas anti-falso-positivo:
    amostra insuficiente e dispersão alta na referência NÃO geram acusação de sobrepreço."""
    if pct is None:
        return "—"
    if n_amostra < _MIN_AMOSTRA:
        return f"referência fraca (n={n_amostra} < {_MIN_AMOSTRA}) — sem base p/ indício de sobrepreço"
    if pct <= 0:
        return "no/abaixo do referencial"
    # dispersão alta na referência: preços do "mesmo" item variam muito (especificação/quantidade/região
    # heterogêneas) — um desvio moderado cai no ruído; só desvio extremo (>+50%) sobrevive como indício.
    if iqr_ratio is not None and iqr_ratio >= _IQR_DISPERSAO and pct < 50:
        return "dispersão alta na referência (itens heterogêneos) — indício FRACO, verificar especificação"
    if pct < 15:
        return "dentro da faixa usual (até +15%)"
    if pct < 30:
        return "atenção (+15% a +30%)"
    return "INDÍCIO DE SOBREPREÇO (> +30% vs mediana)"


async def sobrepreco(codigo_catmat: int, valor_pago: Optional[float] = None,
                     servico: bool = False, max_paginas: int = 2) -> dict:
    """Compara um valor pago com a mediana de referência do item (CATMAT/CATSER).

    Retorna {ok, codigo, servico, n_amostra, mediana_ref, p25, p75, valor_pago, pct,
    classificacao, fonte}. Se sem amostra: mediana_ref=None, fonte='INDISPONÍVEL'.
    """
    precos = await _coletar_precos(int(codigo_catmat), servico, max_paginas)
    if not precos:
        return {
            "ok": True, "codigo": codigo_catmat, "servico": servico, "n_amostra": 0,
            "mediana_ref": None, "valor_pago": valor_pago, "pct": None, "classificacao": "—",
            "fonte": "INDISPONÍVEL: sem amostra no Compras Dados Abertos para este CATMAT/CATSER",
        }
    mediana = statistics.median(precos)
    quantis = statistics.quantiles(precos, n=4) if len(precos) >= 4 else [mediana, mediana, mediana]
    p25, p75 = quantis[0], quantis[2]
    # razão interquartílica como medida de dispersão da referência (robusta a outliers); None se p25<=0.
    iqr_ratio = round(p75 / p25, 2) if p25 and p25 > 0 else None
    pct = None
    if valor_pago and mediana > 0:
        pct = round((float(valor_pago) - mediana) / mediana * 100, 1)
    return {
        "ok": True, "codigo": codigo_catmat, "servico": servico, "n_amostra": len(precos),
        "mediana_ref": round(mediana, 2), "p25": round(p25, 2), "p75": round(p75, 2),
        "iqr_ratio": iqr_ratio, "amostra_suficiente": len(precos) >= _MIN_AMOSTRA,
        "valor_pago": valor_pago, "pct": pct,
        "classificacao": _classificar(pct, n_amostra=len(precos), iqr_ratio=iqr_ratio),
        "fonte": "Compras Dados Abertos (pesquisa de preço por CATMAT/CATSER)",
        "_nota": "Indício a verificar (especificação/quantidade/região podem justificar diferença), nunca acusação.",
    }
