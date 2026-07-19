# -*- coding: utf-8 -*-
"""Camada física OSM (Task 1.3): Nominatim (geocode) + Overpass (edificação no ponto).

Local-first: com `NOMINATIM_LOCAL_URL`/`OVERPASS_URL` no env usa a instância própria (ilimitada —
ver deploy/nominatim/); sem env cai nos serviços públicos com throttle educado (1 req/s no Nominatim)
e User-Agent identificado. HONESTIDADE: geocode que falha/0 resultados → None (INDISPONÍVEL, nunca
lat/lon 0); Overpass com erro de rede → {apuravel: False} (nunca finge terreno vazio).

Cache: reusa o padrão da camada providers (CacheSQLite → data/providers_cache.db), TTL 90 dias —
endereço e edificação quase não mudam. Falha de rede NÃO é cacheada (só resposta real).
"""
from __future__ import annotations

import os
import threading
import time

from compliance_agent.providers.base import CacheSQLite, Resultado, agora_iso

_UA = "JFN-fiscalizacao/1.0 (gabinete RJ)"
_TTL = 90 * 86400  # 90 dias
_NOMINATIM_PUBLICO = "https://nominatim.openstreetmap.org"
_OVERPASS_PUBLICO = "https://overpass-api.de/api/interpreter"

_cache: CacheSQLite | None = None
_cache_lock = threading.Lock()
_ult_publico = [0.0]  # throttle do Nominatim público (1 req/s)


def _get_cache() -> CacheSQLite:
    global _cache
    with _cache_lock:
        if _cache is None:
            _cache = CacheSQLite()
        return _cache


def _throttle_publico() -> None:
    dt = time.monotonic() - _ult_publico[0]
    if dt < 1.0:
        time.sleep(1.0 - dt)
    _ult_publico[0] = time.monotonic()


def _precisao(osm_type: str, classe: str) -> str:
    """rooftop|street|city derivado de osm_type/class: building ou footprint (way) = rooftop;
    highway = centroide de rua; resto (place/boundary/node coarse) = city."""
    if classe == "building":
        return "rooftop"
    if classe == "highway":
        return "street"
    if osm_type == "way":
        return "rooftop"  # footprint de edificação/lote
    return "city"


def geocodificar(endereco: str) -> dict | None:
    """Nominatim → {lat, lon, precisao, fonte} ou None (falha/0 resultados = INDISPONÍVEL, não 0)."""
    if not (endereco or "").strip():
        return None
    local = (os.environ.get("NOMINATIM_LOCAL_URL") or "").rstrip("/")
    fonte = "nominatim_local" if local else "nominatim_publico"
    cache = _get_cache()
    k = cache.chave("geo:nominatim", {"q": endereco.strip()})
    hit = cache.get(k, _TTL)
    if hit is not None:
        return dict(hit["dados"]) if hit["dados"] else None  # None cacheado = "não localizado" real
    try:
        import httpx
    except Exception:
        return None
    params = {"q": endereco, "format": "jsonv2", "addressdetails": 1, "limit": 1,
              "countrycodes": "br"}
    if not local:
        _throttle_publico()
    try:
        r = httpx.get(f"{local or _NOMINATIM_PUBLICO}/search", params=params,
                      headers={"User-Agent": _UA}, timeout=15)
        if r.status_code != 200:
            return None  # indisponibilidade NÃO é cacheada
        data = r.json()
    except Exception:
        return None
    if not data:
        cache.set(k, Resultado(True, None, fonte, agora_iso()))  # "não achou" é resposta real
        return None
    f = data[0]
    try:
        out = {"lat": float(f["lat"]), "lon": float(f["lon"]),
               "precisao": _precisao((f.get("osm_type") or "").lower(),
                                     (f.get("category") or f.get("class") or "").lower()),
               "fonte": fonte}
    except (KeyError, TypeError, ValueError):
        return None
    cache.set(k, Resultado(True, out, fonte, agora_iso()))
    return out


def edificacao_no_ponto(lat: float, lon: float, raio_m: int = 60) -> dict:
    """Overpass → {tem_building, tem_shop, tem_office, tags:[...], apuravel:True}.
    Erro de rede/timeout → {apuravel: False} (nunca finge terreno vazio)."""
    cache = _get_cache()
    k = cache.chave("geo:overpass", {"lat": round(float(lat), 6), "lon": round(float(lon), 6),
                                     "raio_m": raio_m})
    hit = cache.get(k, _TTL)
    if hit is not None:
        return dict(hit["dados"])
    try:
        import httpx
    except Exception:
        return {"apuravel": False}
    q = (f"[out:json][timeout:15];("
         f"way(around:{raio_m},{lat},{lon})[building];"
         f"node(around:{raio_m},{lat},{lon})[shop];"
         f"node(around:{raio_m},{lat},{lon})[office];"
         f"way(around:{raio_m},{lat},{lon})[shop];"
         f");out tags 20;")
    url = os.environ.get("OVERPASS_URL") or _OVERPASS_PUBLICO
    try:
        r = httpx.post(url, data={"data": q}, headers={"User-Agent": _UA}, timeout=20)
        if r.status_code != 200:
            return {"apuravel": False}
        els = (r.json() or {}).get("elements", [])
    except Exception:
        return {"apuravel": False}
    tags = [e.get("tags") or {} for e in els]
    out = {"tem_building": any("building" in t for t in tags),
           "tem_shop": any("shop" in t for t in tags),
           "tem_office": any("office" in t for t in tags),
           "tags": tags, "apuravel": True}
    cache.set(k, Resultado(True, out, "overpass", agora_iso()))
    return out
