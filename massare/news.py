# -*- coding: utf-8 -*-
"""Notícia/sentimento de mercado — JFN 2.0, Onda 8 (Massare; o coração do que faltava).

GDELT DOC 2.0 como motor primário (grátis, sem chave, ~15 min, multilíngue, com tom). Captura
manchetes por tema (China/commodities, energia, conflito, política monetária) com a fonte e o tom.

Honesto: sinal de NARRATIVA (entra no motor de teses da Onda 9), não recomendação; sempre fonte+data.
"""
from __future__ import annotations

import httpx

_GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"


def coletar(tema: str, janela: str = "3d", max_artigos: int = 15) -> dict:
    """Manchetes recentes sobre um tema (GDELT). {ok, tema, artigos:[{titulo,fonte,data,url,tom}]}."""
    try:
        r = httpx.get(_GDELT, params={
            "query": tema, "mode": "ArtList", "format": "json",
            "maxrecords": max_artigos, "timespan": janela, "sort": "DateDesc",
        }, headers={"User-Agent": "JFN-Massare/2.0"}, timeout=25)
        if r.status_code != 200:
            return {"ok": False, "erro": f"GDELT HTTP {r.status_code}"}
        arts = (r.json() or {}).get("articles", []) or []
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": f"GDELT: {str(e)[:80]}"}

    artigos = [{
        "titulo": a.get("title", "")[:200],
        "fonte": a.get("domain", ""),
        "data": a.get("seendate", "")[:8],
        "url": a.get("url", ""),
        "lingua": a.get("language", ""),
        "tom": a.get("tone"),  # GDELT inclui tom em alguns modos; None se ausente
    } for a in arts]
    return {"ok": True, "tema": tema, "n": len(artigos), "artigos": artigos,
            "_fonte": "GDELT DOC 2.0 (grátis, sem chave)",
            "_nota": "Sinal de narrativa/mídia (não recomendação); fonte+data por item."}


def boletim_temas(temas: list[str] | None = None, janela: str = "2d", por_tema: int = 5) -> dict:
    """Boletim multi-tema (commodities/China, energia, política monetária, Brasil)."""
    temas = temas or ["China economy stimulus", "oil energy prices",
                      "Federal Reserve interest rates", "Brazil economy fiscal"]
    blocos = []
    for t in temas:
        r = coletar(t, janela=janela, max_artigos=por_tema)
        if r.get("ok"):
            blocos.append({"tema": t, "artigos": r["artigos"]})
    return {"ok": True, "blocos": blocos, "_fonte": "GDELT DOC 2.0",
            "_nota": "Narrativas vivas p/ o motor de teses (Onda 9); indício de mídia, não recomendação."}
