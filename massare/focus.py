# -*- coding: utf-8 -*-
"""Boletim Focus (BCB/Olinda) — JFN 2.0, Onda 8 (Massare macro forward-looking).

Expectativas de mercado (mediana de ~150 instituições) para Selic, IPCA, PIB e câmbio,
direto da API Olinda do Banco Central via `python-bcb` — SEM chave, grátis. Feature de
"surpresa" = realizado − mediana Focus (alimenta o modelo do Massare).

Honesto: é EXPECTATIVA (forward-looking), não previsão garantida; sempre data + nº de respondentes.
"""
from __future__ import annotations

from datetime import datetime

_INDICADORES = {
    "Selic": "% a.a.", "IPCA": "% a.a.", "PIB Total": "% a.a.", "Câmbio": "R$/US$",
}


def _ano_corrente() -> str:
    # data atual vem do ambiente; aqui só formata o ano de referência das expectativas
    return str(datetime.now().year)


def boletim(ano: str | None = None) -> dict:
    """Mediana das expectativas anuais para o ano de referência. {ok, ano, indicadores, asof}."""
    ano = ano or _ano_corrente()
    try:
        from bcb import Expectativas
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": f"python-bcb indisponível: {e}"}

    em = Expectativas()
    ep = em.get_endpoint("ExpectativasMercadoAnuais")
    out = {}
    asof = None
    for ind in _INDICADORES:
        try:
            df = (ep.query()
                  .filter(ep.Indicador == ind)
                  .filter(ep.DataReferencia == ano)
                  .orderby(ep.Data.desc())
                  .limit(1).collect())
            if not df.empty:
                row = df.iloc[0]
                out[ind] = {"mediana": round(float(row["Mediana"]), 2),
                            "respondentes": int(row.get("numeroRespondentes", 0) or 0),
                            "unidade": _INDICADORES[ind]}
                asof = str(row["Data"])[:10]
        except Exception:  # noqa: BLE001
            out[ind] = {"_nota": "INDISPONÍVEL"}
    if not any("mediana" in v for v in out.values()):
        return {"ok": True, "ano": ano, "indicadores": out,
                "_nota": "INDISPONÍVEL: Focus não retornou dados (rede/API BCB)."}
    return {"ok": True, "ano": ano, "asof": asof, "indicadores": out,
            "_fonte": "BCB/Olinda Expectativas (Focus) via python-bcb (sem chave)",
            "_nota": "Expectativa de mercado (mediana), não previsão garantida; surpresa = realizado − mediana."}
