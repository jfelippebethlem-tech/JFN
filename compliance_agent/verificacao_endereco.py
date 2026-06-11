# -*- coding: utf-8 -*-
"""Verificação de REALIDADE do endereço da sede — bate o endereço declarado com o mapa e checa se o
ponto é **terreno não edificado (baldio), residência simples** ou imóvel comercial real.

Três sinais HONESTOS e grátis (sem chave), proxies do que um diligenciador veria in loco:
  1. **Geocode-match (Nominatim/OSM)** — o endereço declarado resolve? bate o MUNICÍPIO declarado? Endereço
     que não resolve, ou resolve em município diferente, é indício de sede inexistente/fictícia.
  2. **Edificação no ponto (Overpass/OSM)** — há *footprint* de prédio no raio do ponto? `landuse` é de área
     vaga (brownfield/greenfield/farmland/grass/construction)? Ausência de edificação + uso vago = indício de
     **terreno não edificado (baldio)**. ⚠ Cobertura do OSM no BR é incompleta → ausência ≠ prova; sinal MÉDIO,
     nunca CONFIRMADO; confirmar por imagem/in loco.
  3. **Imagem → VLM (opcional)** — se houver chave de Street View/Mapillary, busca a foto do ponto e classifica
     (baldio / barraco / casa simples / comercial) via VLM. Sem chave → INDISPONÍVEL honesto (hook pronto).

Cacheado (7d), rate-limit educado (Nominatim ≤1 req/s; Overpass 1 chamada/ponto). INDISPONÍVEL ≠ baldio;
indício ≠ acusação. Cruzamento de empresas no MESMO endereço fica em `cruzamento.fornecedores_no_mesmo_endereco`
(hipótese H-COEND do motor de DD).
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path

_CACHE_FILE = Path("data") / "endereco_cache.json"
_CACHE_TTL = 30 * 86400  # endereço de sede quase não muda → cache longo (poupa as fontes OSM)
_UA = "JFN-Compliance/1.0 (controle externo; fiscalizacao legitima)"
# Estado de back-off: ao tomar 429/5xx das fontes OSM, sobe o piso de espera p/ não levar bloqueio.
_backoff = {"ate": 0.0, "nivel": 0}
_LANDUSE_VAGO = {"brownfield", "greenfield", "farmland", "grass", "meadow", "construction",
                 "vacant", "scrub", "forest", "orchard", "vineyard"}
_TIPO_RESID = {"house", "residential", "apartments", "dormitory", "terrace", "bungalow"}
_TIPO_COMERCIAL = {"commercial", "retail", "industrial", "office", "warehouse", "supermarket"}

_cache: dict | None = None
_ult_nominatim = [0.0]


def em_backoff() -> float:
    """Segundos restantes de back-off (0 se livre). O sweep deve respeitar antes de seguir."""
    return max(0.0, _backoff["ate"] - time.time())


def _marca_backoff() -> None:
    """Escalona o back-off ao tomar 429/5xx (30s, 60s, 120s, … teto 600s)."""
    _backoff["nivel"] = min(_backoff["nivel"] + 1, 5)
    _backoff["ate"] = time.time() + min(30 * (2 ** (_backoff["nivel"] - 1)), 600)


def _limpa_backoff() -> None:
    if _backoff["nivel"]:
        _backoff["nivel"] = 0
        _backoff["ate"] = 0.0


def _norm(s: str) -> str:
    s = (s or "").upper().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


def _carrega_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_CACHE_FILE.read_text("utf-8")) if _CACHE_FILE.exists() else {}
        except Exception:
            _cache = {}
    return _cache


def _salva_cache() -> None:
    try:
        _CACHE_FILE.parent.mkdir(exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(_cache, ensure_ascii=False), "utf-8")
    except Exception:
        pass


def geocodificar(endereco: str, municipio: str | None = None, uf: str | None = None,
                 cep: str | None = None) -> dict:
    """Nominatim → {ok, lat, lon, classe, tipo, display, municipio_geo, bate_municipio, motivo}."""
    base = {"ok": False, "lat": None, "lon": None, "classe": "", "tipo": "", "display": "",
            "municipio_geo": "", "bate_municipio": None, "motivo": ""}
    try:
        import httpx
    except Exception:
        return {**base, "motivo": "httpx ausente"}
    consulta = ", ".join(p for p in [endereco, municipio, uf, "Brasil"] if p)
    params = {"q": consulta, "format": "jsonv2", "addressdetails": 1, "limit": 1, "countrycodes": "br"}
    # rate-limit Nominatim (política de uso: ≤1 req/s)
    dt = time.time() - _ult_nominatim[0]
    if dt < 1.1:
        time.sleep(1.1 - dt)
    _ult_nominatim[0] = time.time()
    try:
        r = httpx.get("https://nominatim.openstreetmap.org/search", params=params,
                      headers={"User-Agent": _UA}, timeout=15)
        if r.status_code in (429, 503) or r.status_code >= 500:
            _marca_backoff()
            return {**base, "motivo": f"HTTP {r.status_code} (back-off)"}
        if r.status_code != 200:
            return {**base, "motivo": f"HTTP {r.status_code}"}
        data = r.json()
        _limpa_backoff()
    except Exception as e:  # noqa: BLE001
        return {**base, "motivo": str(e)[:60]}
    if not data:
        return {**base, "motivo": "endereço não localizado"}
    f = data[0]
    addr = f.get("address") or {}
    mun_geo = (addr.get("city") or addr.get("town") or addr.get("municipality")
               or addr.get("village") or "")
    bate = None
    if municipio and mun_geo:
        bate = _norm(municipio) in _norm(mun_geo) or _norm(mun_geo) in _norm(municipio)
    return {"ok": True, "lat": float(f["lat"]), "lon": float(f["lon"]),
            "classe": (f.get("category") or f.get("class") or "").lower(),
            "tipo": (f.get("type") or "").lower(), "display": f.get("display_name", ""),
            "municipio_geo": mun_geo, "bate_municipio": bate, "motivo": ""}


def edificacao_no_ponto(lat: float, lon: float, raio: int = 35) -> dict:
    """Overpass/OSM → {ok, tem_predio, n_predios, landuse_vago, landuses, motivo}. Sem chave."""
    base = {"ok": False, "tem_predio": None, "n_predios": 0, "landuse_vago": None,
            "landuses": [], "motivo": ""}
    try:
        import httpx
    except Exception:
        return {**base, "motivo": "httpx ausente"}
    q = (f"[out:json][timeout:15];("
         f'way(around:{raio},{lat},{lon})["building"];'
         f'way(around:{raio},{lat},{lon})["landuse"];'
         f'node(around:{raio},{lat},{lon})["building"];'
         f");out tags center 40;")
    try:
        r = httpx.post("https://overpass-api.de/api/interpreter", data={"data": q},
                       headers={"User-Agent": _UA}, timeout=30)
        if r.status_code in (429, 504) or r.status_code >= 500:
            _marca_backoff()
            return {**base, "motivo": f"HTTP {r.status_code} (back-off)"}
        if r.status_code != 200:
            return {**base, "motivo": f"HTTP {r.status_code}"}
        els = (r.json() or {}).get("elements", [])
        _limpa_backoff()
    except Exception as e:  # noqa: BLE001
        return {**base, "motivo": str(e)[:60]}
    n_predios = sum(1 for e in els if "building" in (e.get("tags") or {}))
    landuses = sorted({(e.get("tags") or {}).get("landuse", "") for e in els if (e.get("tags") or {}).get("landuse")})
    vago = bool(landuses) and all(lu in _LANDUSE_VAGO for lu in landuses)
    return {"ok": True, "tem_predio": n_predios > 0, "n_predios": n_predios,
            "landuse_vago": vago, "landuses": landuses, "motivo": ""}


def _classificar_visual(lat: float, lon: float) -> dict:
    """Hook imagem→VLM (Street View/Mapillary + gemini). Ativa só com chave; senão INDISPONÍVEL honesto."""
    chave = (os.environ.get("GOOGLE_MAPS_KEY", "") or os.environ.get("STREETVIEW_KEY", "")
             or os.environ.get("MAPILLARY_TOKEN", "")).strip()
    if not chave:
        return {"ok": False, "classe": "", "motivo": "INDISPONIVEL (sem chave de imagem de rua — "
                "defina GOOGLE_MAPS_KEY/MAPILLARY_TOKEN p/ classificar baldio/barraco/casa via VLM)"}
    # Implementação ativável: buscar imagem do ponto e classificar via VLM (gemini/OpenRouter).
    return {"ok": False, "classe": "", "motivo": "INDISPONIVEL (classificador visual ainda não ativado)"}


def analisar_endereco(endereco: str, municipio: str | None = None, uf: str | None = None,
                      cep: str | None = None, *, usar_overpass: bool = True,
                      usar_imagem: bool = False, forcar_update: bool = False) -> dict:
    """Orquestra geocode + edificação (+ imagem) → veredito honesto sobre a realidade da sede.

    Retorna {status, nivel, evidencia, peso, estado, sinais:{geocode,edificacao,imagem}}.
    status: INDICIO | AFASTADO | INDISPONIVEL (nunca CONFIRMADO só por OSM)."""
    chave = _norm(" ".join(p for p in [endereco, municipio, uf, cep] if p))
    cache = _carrega_cache()
    if chave and not forcar_update:
        ent = cache.get(chave)
        if ent and (time.time() - ent.get("_ts", 0)) < _CACHE_TTL:
            return {k: v for k, v in ent.items() if k != "_ts"}

    g = geocodificar(endereco, municipio, uf, cep)
    sinais = {"geocode": g, "edificacao": {}, "imagem": {}}
    if not g["ok"]:
        out = {"status": "INDICIO", "nivel": "MEDIO", "peso": 8, "estado": "verificado (não resolvido)",
               "evidencia": (f"Endereço da sede não localizado na base cartográfica aberta (OpenStreetMap) — "
                             f"'{endereco}'. Endereço não-resolvível merece apuração de existência física "
                             "(possível sede inexistente/fictícia) — confirmar por imagem/in loco."),
               "sinais": sinais}
        cache[chave] = {**out, "_ts": time.time()}
        _salva_cache()
        return out

    # endereço resolve mas em município diferente do declarado → forte indício de incoerência
    if g["bate_municipio"] is False:
        out = {"status": "INDICIO", "nivel": "ALTO", "peso": 12,
               "estado": f"verificado (município diverge: declarado≠{g['municipio_geo']})",
               "evidencia": (f"O endereço declarado resolve no mapa em **{g['municipio_geo']}**, divergente do "
                             f"município declarado ('{municipio}'). Incoerência entre a sede declarada e a "
                             "localização real é indício de endereço fictício — apurar."),
               "sinais": sinais}
        cache[chave] = {**out, "_ts": time.time()}
        _salva_cache()
        return out

    ed = edificacao_no_ponto(g["lat"], g["lon"]) if usar_overpass else {"ok": False, "motivo": "não solicitado"}
    sinais["edificacao"] = ed
    if usar_imagem:
        sinais["imagem"] = _classificar_visual(g["lat"], g["lon"])

    # terreno não edificado (baldio): sem prédio no ponto E/ou landuse de área vaga
    if ed.get("ok") and ed.get("tem_predio") is False:
        nivel = "MEDIO"
        extra = (f" Uso do solo mapeado: {', '.join(ed['landuses'])}." if ed.get("landuses") else "")
        baldio = " e o uso do solo é de área não edificada" if ed.get("landuse_vago") else ""
        out = {"status": "INDICIO", "nivel": nivel, "peso": 10,
               "estado": "verificado (sem edificação mapeada)",
               "evidencia": (f"No ponto geocodificado da sede NÃO há edificação mapeada no OpenStreetMap{baldio} — "
                             f"indício de **terreno não edificado (baldio)** ou sede inexistente.{extra} "
                             "⚠ A cobertura do OSM no Brasil é incompleta; confirmar por imagem de satélite/"
                             "rua ou diligência in loco antes de concluir."),
               "sinais": sinais}
        cache[chave] = {**out, "_ts": time.time()}
        _salva_cache()
        return out

    # imóvel residencial no ponto → corrobora 'sede em residência'
    if g["tipo"] in _TIPO_RESID or (ed.get("ok") and ed.get("tem_predio") and g["classe"] == "place"):
        out = {"status": "INDICIO", "nivel": "MEDIO", "peso": 6, "estado": "verificado (residencial)",
               "evidencia": (f"A geocodificação aponta feição residencial ('{g['classe']}/{g['tipo']}') no "
                             "endereço da sede. Corrobora natureza residencial da sede — verificar operação "
                             "física real (estoque, funcionários, instalações)."),
               "sinais": sinais}
        cache[chave] = {**out, "_ts": time.time()}
        _salva_cache()
        return out

    # imóvel comercial/industrial com edificação → afasta (parece sede real)
    out = {"status": "AFASTADO", "nivel": "BAIXO", "peso": 0,
           "estado": f"verificado ({g['classe']}/{g['tipo']}; {ed.get('n_predios', 0)} edificação(ões))",
           "evidencia": ("Endereço resolve no mapa e há edificação compatível com uso comercial/real no ponto — "
                         "sem indício de baldio/inexistência por esta verificação."),
           "sinais": sinais}
    cache[chave] = {**out, "_ts": time.time()}
    _salva_cache()
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Verifica realidade do endereço (geocode + edificação/baldio)")
    ap.add_argument("endereco")
    ap.add_argument("--municipio", default="")
    ap.add_argument("--uf", default="")
    ap.add_argument("--cep", default="")
    a = ap.parse_args()
    print(json.dumps(analisar_endereco(a.endereco, a.municipio, a.uf, a.cep), ensure_ascii=False, indent=2))
