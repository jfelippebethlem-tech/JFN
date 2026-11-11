# -*- coding: utf-8 -*-
"""Geografia de referência: os 92 municípios do RJ (IBGE) e os bairros → RA → AP do Rio (Data.Rio).

Fontes versionadas (geradas por `tools/v61_geo.sh`):
  · `dados/municipios_rj.json` — IBGE, API de localidades v1;
  · `static/assets/geo/rio-aps.topo.json` — "Limite de Bairros" do Data.Rio/IPP (167 bairros, 33 RAs, 5 APs).
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_REPO = _AQUI.parent.parent
RIO = "3304557"


def norm(s: str | None) -> str:
    """MAIÚSCULAS, sem acento, só letras/dígitos separados por UM espaço ("Varre-Sai" → "VARRE SAI")."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii").upper()
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


@lru_cache(maxsize=1)
def municipios() -> list[dict]:
    """[{cod_ibge, nome, mesorregiao, …}] — os 92, ordenados por código."""
    d = json.loads((_AQUI / "dados" / "municipios_rj.json").read_text(encoding="utf-8"))
    return d["municipios"]


@lru_cache(maxsize=1)
def nome_municipio() -> dict[str, str]:
    return {m["cod_ibge"]: m["nome"] for m in municipios()}


@lru_cache(maxsize=1)
def bairros() -> list[dict]:
    """[{bairro, ra, codra, ap}] dos 167 bairros oficiais do Rio."""
    t = json.loads((_REPO / "static" / "assets" / "geo" / "rio-aps.topo.json").read_text(encoding="utf-8"))
    return [dict(g["properties"]) for g in t["objects"]["bairros"]["geometries"]]


@lru_cache(maxsize=1)
def ras_por_ap() -> dict[int, list[str]]:
    out: dict[int, set] = {}
    for b in bairros():
        out.setdefault(int(b["ap"]), set()).add(b["ra"])
    return {ap: sorted(v) for ap, v in sorted(out.items())}
