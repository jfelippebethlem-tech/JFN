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


def _cep_fmt(cep: str | None) -> str:
    d = re.sub(r"\D", "", str(cep or ""))
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else ""


def _variantes_consulta(endereco: str, municipio: str | None, uf: str | None, cep: str | None) -> list[str]:
    """Variações de busca, da mais específica à menos — periferia mal-mapeada exige usar o CEP e cair p/ a rua.

    Lição NEW LINK (2026-06-11): 'TAPAJOS, 60, ...' falha no Nominatim, mas com CEP e prefixo 'Rua' resolve —
    não confundir cobertura ruim do OSM com endereço inexistente."""
    cep = _cep_fmt(cep)
    via = (endereco or "").split(",")[0].strip()  # só o logradouro (sem número/bairro)
    tem_tipo = bool(re.match(r"(?i)\s*(rua|av|avenida|estrada|travessa|rod|alameda|praca|praça|r\.|estr)\b", via))
    via_pref = via if tem_tipo or not via else f"Rua {via}"
    cauda = ", ".join(p for p in [municipio, uf, "Brasil"] if p)
    vs = []
    if endereco:
        vs.append(", ".join(p for p in [endereco, municipio, uf, cep, "Brasil"] if p))
        if not tem_tipo:
            vs.append(", ".join(p for p in [f"Rua {endereco}", municipio, uf, cep, "Brasil"] if p))
        vs.append(", ".join(p for p in [via_pref, cep, cauda] if p))          # logradouro + CEP
        vs.append(", ".join(p for p in [via_pref, cauda] if p))                # logradouro só
    if cep:
        vs.append(f"{cep}, Brasil")                                           # CEP puro (centroide da rua)
    # dedup preservando ordem
    vis, seen = [], set()
    for v in vs:
        if v and v not in seen:
            seen.add(v)
            vis.append(v)
    return vis


def geocodificar(endereco: str, municipio: str | None = None, uf: str | None = None,
                 cep: str | None = None) -> dict:
    """Nominatim com fallback de variações (usa o CEP) → {ok, lat, lon, classe, tipo, display,
    municipio_geo, bate_municipio, exato, motivo}. `exato`=False quando caiu p/ a rua/CEP (não o nº)."""
    base = {"ok": False, "lat": None, "lon": None, "classe": "", "tipo": "", "display": "",
            "municipio_geo": "", "bate_municipio": None, "exato": False, "motivo": ""}
    try:
        import httpx
    except Exception:
        return {**base, "motivo": "httpx ausente"}
    variantes = _variantes_consulta(endereco, municipio, uf, cep)
    data, idx = None, -1
    for i, consulta in enumerate(variantes):
        params = {"q": consulta, "format": "jsonv2", "addressdetails": 1, "limit": 1, "countrycodes": "br"}
        dt = time.time() - _ult_nominatim[0]  # rate-limit Nominatim (≤1 req/s)
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
            d = r.json()
            _limpa_backoff()
        except Exception as e:  # noqa: BLE001
            return {**base, "motivo": str(e)[:60]}
        if d:
            data, idx = d, i
            break
    if not data:
        return {**base, "motivo": "endereço não localizado (nem por logradouro/CEP)"}
    base["exato"] = idx == 0  # só a 1ª variante mira o nº; as demais são logradouro/CEP (centroide)
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
            "municipio_geo": mun_geo, "bate_municipio": bate, "exato": base["exato"], "motivo": ""}


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


# Classes do veredito visual (auditoria de fachada): o que predomina no ponto/entorno do endereço.
_CLASSES_VISUAIS = ["terreno_baldio", "area_aberta_rural", "construcao_precaria_barraco",
                    "casa_residencial", "predio_residencial", "comercial_industrial",
                    "galpao_logistico", "indeterminado"]
# Classes que reforçam indício de fachada/inexistência operacional:
_CLASSE_INDICIO = {"terreno_baldio", "area_aberta_rural", "construcao_precaria_barraco"}


def _fetch_satelite_esri(lat: float, lon: float, delta: float = 0.0009) -> bytes | None:
    """Imagem de satélite do entorno (Esri World Imagery — pública, sem chave). PNG ~600px ou None."""
    try:
        import httpx
    except Exception:
        return None
    bbox = f"{lon - delta},{lat - delta},{lon + delta},{lat + delta}"
    url = ("https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/export"
           f"?bbox={bbox}&bboxSR=4326&imageSR=3857&size=640,640&format=png&f=image")
    try:
        r = httpx.get(url, headers={"User-Agent": _UA}, timeout=25)
        return r.content if (r.status_code == 200 and r.content[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0")) else None
    except Exception:
        return None


# ── Teto de requisições PAGAS do Street View (não gerar cobrança) ──
_SV_QUOTA_FILE = Path("data") / "streetview_quota.json"
_SV_QUOTA_JANELA = 31 * 86400  # janela rolante de 31 dias


def _fontes_rua_ordenadas() -> list[str]:
    """Ordem das fontes RENTE AO CHÃO, parametrizável por env `IMG_FONTE_ORDEM` (csv).

    ⚠ MAPILLARY/ESRI APOSENTADOS (2026-06-14): cobertura ruim e fotos efêmeras; a fonte ATIVA de fachada
    passou a ser o **Google Street View via Maps Embed API** (grátis/ilimitada, `tools/fachada_streetview_
    sweep.py`). Aqui o default virou **só `streetview`** (Static, capado a 9999/31d — fallback p/ o caminho
    `analisar_endereco(usar_imagem=True)`). Mapillary só entra se EXPLICITAMENTE pedido via `IMG_FONTE_ORDEM`
    (mantido como hook, não no caminho ativo)."""
    ordem = [s.strip().lower() for s in os.environ.get("IMG_FONTE_ORDEM", "streetview").split(",")
             if s.strip() in ("mapillary", "streetview")]
    return ordem or ["streetview"]


def _streetview_max() -> int:
    try:
        return int(os.environ.get("STREETVIEW_MAX_31D", "9999"))  # teto p/ ficar no crédito grátis
    except Exception:
        return 9999


def _streetview_consome_cota() -> bool:
    """True se ainda há cota de requisição PAGA na janela de 31 dias; consome 1. Persiste em disco.
    Conta SÓ a requisição de IMAGEM (paga) — a checagem de cobertura (metadata) é grátis e não entra."""
    try:
        st = json.loads(_SV_QUOTA_FILE.read_text("utf-8")) if _SV_QUOTA_FILE.exists() else {}
    except Exception:
        st = {}
    now = time.time()
    ini = st.get("janela_inicio", 0)
    if not ini or (now - ini) > _SV_QUOTA_JANELA:
        st = {"janela_inicio": now, "count": 0}  # rola a janela
    if st.get("count", 0) >= _streetview_max():
        return False  # teto atingido → não dispara requisição paga (cai p/ Mapillary/satélite)
    st["count"] = st.get("count", 0) + 1
    try:
        _SV_QUOTA_FILE.parent.mkdir(exist_ok=True)
        _SV_QUOTA_FILE.write_text(json.dumps(st), "utf-8")
    except Exception:
        pass
    return True


def _fetch_streetview_google(lat: float, lon: float, chave: str) -> bytes | None:
    """Foto de rua (Google Street View Static). HONESTO COM A FATURA: 1) checa COBERTURA no endpoint
    `metadata` (GRÁTIS) — se ZERO_RESULTS, nem dispara a requisição paga; 2) só então consome a cota de
    31 dias (teto `STREETVIEW_MAX_31D`, default 9999) e baixa a imagem (paga). JPG ou None."""
    try:
        import httpx
    except Exception:
        return None
    # 1) cobertura via metadata — GRÁTIS (não conta p/ billing); evita gastar requisição em ponto sem foto
    try:
        m = httpx.get("https://maps.googleapis.com/maps/api/streetview/metadata",
                      params={"location": f"{lat},{lon}", "key": chave}, timeout=15)
        if m.status_code != 200 or (m.json() or {}).get("status") != "OK":
            return None  # ZERO_RESULTS / NOT_FOUND → sem cobertura; não gera cobrança
    except Exception:
        return None
    # 2) há cobertura → consome cota paga (respeita o teto 31d) e baixa a imagem
    if not _streetview_consome_cota():
        return None
    url = ("https://maps.googleapis.com/maps/api/streetview"
           f"?size=640x480&location={lat},{lon}&fov=80&key={chave}")
    try:
        r = httpx.get(url, timeout=20)
        return r.content if (r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff") else None
    except Exception:
        return None


def _mapillary_busca(token: str, lat: float, lon: float, raio_m: float):
    """Consulta a Mapillary num bbox ~raio_m. Em densidade alta a API responde 500 'reduce data' → o
    chamador encolhe o raio e tenta de novo. Retorna (status, data) onde status: 'ok'|'vazio'|'denso'|'erro'."""
    try:
        import math

        import httpx
    except Exception:
        return ("erro", [])
    dlat = raio_m / 111_000.0
    dlon = raio_m / (111_000.0 * max(0.1, math.cos(math.radians(lat))))
    bbox = f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}"
    try:
        r = httpx.get("https://graph.mapillary.com/images",
                      params={"access_token": token, "bbox": bbox, "limit": 30,
                              "fields": "id,thumb_1024_url,computed_geometry"},
                      headers={"User-Agent": _UA}, timeout=20)
        if r.status_code == 500 and "reduce the amount" in (r.text or "").lower():
            return ("denso", [])  # bbox cobre features demais → encolher
        if r.status_code != 200:
            return ("erro", [])
        return ("ok", (r.json() or {}).get("data") or [])
    except Exception:
        return ("erro", [])


def _fetch_mapillary(lat: float, lon: float, token: str, raio_m: float = 120.0) -> bytes | None:
    """Foto de rua do ponto via **Mapillary** (crowdsourced, Meta — token GRÁTIS, sem billing). Pega a
    imagem mais próxima do ponto e baixa o thumb. JPG ou None. É RENTE AO CHÃO (como o Street View) → pode
    distinguir casebre/barraco de prédio comercial mesmo quando há edificação (≠ satélite, que só afasta).
    Cobertura é esparsa (raio default 120m); em zona densa a API pede menos dados → encolhe o raio e retenta."""
    try:
        import httpx  # noqa: F401
    except Exception:
        return None
    data, r = [], raio_m
    for _ in range(4):  # densa demais → encolhe; vazia no raio → expande uma vez
        status, d = _mapillary_busca(token, lat, lon, r)
        if status == "ok" and d:
            data = d
            break
        if status == "denso":
            r = max(25.0, r / 2)
            continue
        if status == "ok" and not d:
            if r >= 250:
                break
            r = min(250.0, r * 2)  # sem cobertura nesse raio → tenta um pouco mais largo
            continue
        return None  # erro de rede
    if not data:
        return None  # sem cobertura Mapillary nesse ponto (comum na periferia) → cai p/ satélite

    def _dist2(img):  # distância² ao ponto (computed_geometry = Point [lon,lat])
        g = (img.get("computed_geometry") or {}).get("coordinates")
        if not g or len(g) < 2:
            return 9e9
        return (g[0] - lon) ** 2 + (g[1] - lat) ** 2
    melhor = min(data, key=_dist2)
    url = melhor.get("thumb_1024_url")
    if not url:
        return None
    try:
        import httpx
        r2 = httpx.get(url, headers={"User-Agent": _UA}, timeout=25)
        return r2.content if (r2.status_code == 200 and r2.content[:3] == b"\xff\xd8\xff") else None
    except Exception:
        return None


def _gemini_vision_sync(img: bytes, mime: str, prompt: str) -> str:
    """Gemini nativo (pool de chaves, tier grátis) com visão. Retorna o texto ou '' se todas falharem."""
    import base64

    import httpx
    try:
        from compliance_agent.direcionamento_cerebro import _gemini_keys
        keys = _gemini_keys()
    except Exception:
        keys = [k.strip() for k in (os.environ.get("GEMINI_API_KEYS", "")
                or os.environ.get("GEMINI_API_KEY", "")).replace(",", " ").split() if k.strip()]
    if not keys:
        return ""
    body = {"contents": [{"role": "user", "parts": [
        {"text": prompt},
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(img).decode()}}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 250, "responseMimeType": "application/json"}}
    for mdl in ("gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-2.5-flash"):
        for key in keys:
            try:
                r = httpx.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{mdl}:generateContent?key={key}",
                    json=body, timeout=40)
                if r.status_code in (429, 401, 403):
                    continue
                if r.status_code == 404:
                    break  # modelo indisponível → próximo modelo
                r.raise_for_status()
                j = r.json()
                return j.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            except Exception:  # noqa: BLE001
                continue
    return ""


def _vlm_classificar(img: bytes, fonte: str, endereco: str = "") -> dict:
    """Classifica a imagem (satélite/rua) via VLM — Gemini nativo (pool) e, em falta, OpenRouter visão."""
    import base64
    if not img:
        return {"ok": False, "motivo": "sem imagem"}
    mime = "image/png" if img[:4] == b"\x89PNG" else "image/jpeg"
    tipo = ("satélite (vista aérea do entorno da quadra)" if fonte == "esri"
            else "foto de rua (Mapillary, rente ao chão)" if fonte == "mapillary"
            else "foto de rua (Street View)")
    prompt = (
        f"Você audita a SEDE de uma empresa fornecedora do poder público. Esta é uma imagem de {tipo} no "
        f"endereço declarado{(' (' + endereco + ')') if endereco else ''}. Classifique o que PREDOMINA no centro "
        "da imagem em UMA destas categorias: terreno_baldio (lote vazio/sem construção), area_aberta_rural "
        "(campo/mato/rural sem edificações), construcao_precaria_barraco (construção precária/favela/barraco), "
        "casa_residencial, predio_residencial, comercial_industrial, galpao_logistico, indeterminado (nuvem/"
        "imagem ruim/ambíguo). Responda SOMENTE JSON: "
        '{"classe":"<categoria>","confianca":<0-1>,"descricao":"<breve, em português>"}')
    txt = _gemini_vision_sync(img, mime, prompt)
    if not txt:  # fallback OpenRouter (visão)
        chave = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if chave:
            modelo = os.environ.get("OPENROUTER_VISION_MODEL", "google/gemini-2.5-flash-lite")
            b64 = base64.b64encode(img).decode()
            messages = [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]}]
            try:
                from compliance_agent.llm.free_llm import OPENROUTER_BASE, _openai_compat_chat_sync
                txt = _openai_compat_chat_sync(OPENROUTER_BASE, chave, modelo, messages, max_tokens=220)
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "motivo": f"VLM erro: {str(e)[:60]}"}
    if not txt:
        return {"ok": False, "motivo": "VLM indisponível (Gemini pool + OpenRouter falharam)"}
    m = re.search(r"\{.*\}", txt or "", re.DOTALL)
    if not m:
        return {"ok": False, "motivo": "VLM sem JSON"}
    try:
        d = json.loads(m.group(0))
    except Exception:
        return {"ok": False, "motivo": "VLM JSON inválido"}
    classe = str(d.get("classe", "")).strip().lower()
    if classe not in _CLASSES_VISUAIS:
        classe = "indeterminado"
    return {"ok": True, "classe": classe, "confianca": float(d.get("confianca") or 0),
            "descricao": str(d.get("descricao", ""))[:200]}


def classificar_local_por_imagem(lat: float, lon: float, endereco: str = "",
                                 *, retornar_imagem: bool = False) -> dict:
    """Resolve um endereço por IMAGEM, priorizando o GRÁTIS e rente ao chão (que distingue casebre de prédio):
    **Mapillary** (token grátis) → **Street View** (Google, pago, capado a 9999/31d, fallback) → **satélite
    Esri** (grátis, só ENTORNO). Ordem parametrizável por `IMG_FONTE_ORDEM`. VLM classifica a fachada.

    Retorna {ok, status, nivel, classe, confianca, fonte, evidencia}. status: INDICIO|AFASTADO|INDISPONIVEL.
    HONESTO: o satélite usa coords no nível da rua (±~100m) → veredito do ENTORNO, não do lote exato → só
    AFASTA, nunca acusa. Mapillary/Street View são rente ao chão → podem acusar casebre/baldio (confirmar in loco).

    Se `retornar_imagem=True`, o dict ganha `_img_bytes` (bytes da imagem classificada, ou None) e
    `_img_fonte` (`mapillary`/`streetview`/`esri`) — p/ o chamador SALVAR o print SEM re-buscar a fonte
    (zero requisição/cota extra). Não altera nada do veredito; só anexa os bytes já baixados."""
    base = {"ok": False, "status": "INDISPONIVEL", "nivel": "—", "classe": "", "confianca": 0.0,
            "fonte": "", "evidencia": ""}
    if lat is None or lon is None:
        return {**base, "evidencia": "sem coordenadas p/ buscar imagem"}
    gkey = (os.environ.get("GOOGLE_MAPS_KEY", "") or os.environ.get("STREETVIEW_KEY", "")).strip()
    mly = os.environ.get("MAPILLARY_TOKEN", "").strip()
    # PRIORIDADE PARAMETRIZÁVEL das fontes RENTE AO CHÃO (que distinguem casebre de prédio comercial).
    # Default `mapillary,streetview`: tenta o Mapillary (GRÁTIS) primeiro; o Street View (PAGO, capado a
    # 9999/31d) só é acionado onde o Mapillary NÃO cobre. Trocar a ordem via env `IMG_FONTE_ORDEM`.
    # O satélite Esri (grátis, só ENTORNO → NUNCA acusa) é sempre o último recurso.
    raio_mly = float(os.environ.get("MAPILLARY_RAIO_M", "120") or 120)
    img, fonte = (None, "")
    for src in _fontes_rua_ordenadas():
        if src == "mapillary" and mly:
            img = _fetch_mapillary(lat, lon, mly, raio_m=raio_mly)
            if img is not None:
                fonte = "mapillary"; break
        elif src == "streetview" and gkey:
            img = _fetch_streetview_google(lat, lon, gkey)
            if img is not None:
                fonte = "streetview"; break
    # Satélite Esri APOSENTADO do caminho ATIVO (2026-06-14): só afasta o entorno e induzia alucinação do VLM
    # ("barraco" no Banco do Brasil). Mantido como hook opt-in via env `USAR_SATELITE_ESRI=1` (não no default).
    if img is None and os.environ.get("USAR_SATELITE_ESRI", "").strip() in ("1", "true", "True"):
        img = _fetch_satelite_esri(lat, lon)
        if img is not None:
            fonte = "esri"
    def _ret(d: dict) -> dict:
        """Anexa os bytes da imagem já baixada (sem re-fetch) quando o chamador pediu — p/ salvar o print."""
        if retornar_imagem:
            d = {**d, "_img_bytes": img, "_img_fonte": fonte}
        return d

    if img is None:
        return _ret({**base, "evidencia": "não foi possível obter imagem (Mapillary/Street View/satélite indisponível)"})
    v = _vlm_classificar(img, fonte, endereco)
    if not v.get("ok"):
        return _ret({**base, "fonte": fonte, "evidencia": f"imagem obtida ({fonte}) mas VLM indisponível: {v.get('motivo', '')}"})
    classe, conf, desc = v["classe"], v["confianca"], v.get("descricao", "")
    # PRECISO = imagem RENTE AO CHÃO (mira a fachada do lote: distingue casebre/barraco de prédio comercial).
    # Street View e Mapillary são rente ao chão → podem ACUSAR. Satélite é o entorno (±~100m) → só AFASTA.
    preciso = fonte in ("streetview", "mapillary")
    fonte_lbl = ("Google Street View" if fonte == "streetview"
                 else "Mapillary (foto de rua)" if fonte == "mapillary"
                 else "satélite Esri (entorno da quadra, ±~100m)")

    # ACUSAÇÃO (baldio/barraco/rural) só com fonte PRECISA. Satélite no centroide da rua já classificou
    # o Banco do Brasil como 'barraco' (falso) — imprecisão + alucinação do VLM. Honestidade: não acusar.
    if classe in _CLASSE_INDICIO:
        if preciso:
            _casebre = classe == "construcao_precaria_barraco"
            _qualifica = ("edificação precária/casebre — incompatível com a operação de uma fornecedora do "
                          "Estado mesmo havendo construção" if _casebre
                          else "ausência de edificação compatível com operação")
            return _ret({"ok": True, "status": "INDICIO", "nivel": "ALTO" if conf >= 0.6 else "MEDIO",
                    "classe": classe, "confianca": conf, "fonte": fonte_lbl,
                    "evidencia": (f"{fonte_lbl} (foto rente ao chão) classifica a sede como "
                                  f"**{classe.replace('_', ' ')}** (confiança {conf:.0%}): {desc}. "
                                  f"{_qualifica[0].upper() + _qualifica[1:]} é indício de fachada/inexistência "
                                  "operacional — confirmar in loco.")})
        return _ret({**base, "ok": True, "status": "INDISPONIVEL", "classe": classe, "confianca": conf,
                "fonte": fonte_lbl,
                "evidencia": (f"O satélite do entorno SUGERE '{classe.replace('_', ' ')}', mas a coordenada é no "
                              "nível da rua (imprecisa p/ o lote) — NÃO conclusivo (satélite chega a confundir "
                              "prédio com construção precária). Confirmar por foto de rua (Mapillary/Street View) "
                              "ou diligência in loco antes de qualquer conclusão.")})
    if classe == "indeterminado":
        return _ret({**base, "ok": True, "fonte": fonte_lbl, "classe": classe, "confianca": conf,
                "evidencia": f"Análise visual ({fonte_lbl}) inconclusiva: {desc}."})
    # classes EDIFICADAS (casa/prédio/comercial/galpão) → AFASTAR é seguro (falso-negativo é aceitável; nunca acusa)
    return _ret({"ok": True, "status": "AFASTADO", "nivel": "BAIXO", "classe": classe, "confianca": conf,
            "fonte": fonte_lbl,
            "evidencia": (f"Análise visual ({fonte_lbl}) indica área edificada ({classe.replace('_', ' ')}, "
                          f"confiança {conf:.0%}): {desc}. Compatível com sede real — sem indício visual de fachada.")})


def _classificar_visual(lat: float, lon: float) -> dict:
    """Compat: hook usado no fluxo exato. Delega ao classificador por imagem."""
    return classificar_local_por_imagem(lat, lon)


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

    # ⚠ Match coarse (logradouro/CEP, não o nº) é RUIDOSO p/ município — pode cair em cidade errada por
    # fallback do Nominatim (lição 036100: 83 falsas 'divergências', todas exato=False). NÃO afirmar nada.
    if not g.get("exato"):
        out = {"status": "INDISPONIVEL", "nivel": "BAIXO", "peso": 0,
               "estado": "verificado (logradouro/CEP resolve; nº não geolocalizado)",
               "evidencia": ("O endereço resolve apenas no nível do logradouro/CEP (o número exato não está na "
                             "base cartográfica aberta) — cobertura incompleta; não dá p/ afirmar baldio nem "
                             "divergência de município por esta via. Confirmar por imagem de rua/in loco."),
               "sinais": sinais}
        cache[chave] = {**out, "_ts": time.time()}
        _salva_cache()
        return out

    # ── daqui p/ baixo o geocode mirou o NÚMERO (exato=True) → veredito confiável ──
    # município divergente COM o nº resolvido em cidade diferente da declarada → incoerência real
    if g["bate_municipio"] is False:
        out = {"status": "INDICIO", "nivel": "ALTO", "peso": 12,
               "estado": f"verificado (município diverge: declarado≠{g['municipio_geo']})",
               "evidencia": (f"O número da sede resolve no mapa em **{g['municipio_geo']}**, divergente do "
                             f"município declarado ('{municipio}'). Incoerência entre a sede declarada e a "
                             "localização real é indício de endereço fictício — apurar."),
               "sinais": sinais}
        cache[chave] = {**out, "_ts": time.time()}
        _salva_cache()
        return out

    ed = edificacao_no_ponto(g["lat"], g["lon"]) if usar_overpass else {"ok": False, "motivo": "não solicitado"}
    sinais["edificacao"] = ed
    if usar_imagem:
        vis = _classificar_visual(g["lat"], g["lon"])
        sinais["imagem"] = vis
        # A foto RENTE AO CHÃO (Mapillary/Street View) acusando casebre/baldio/rural PRECEDE o "edificado"
        # do OSM — pedido do dono: mesmo havendo construção, a fachada pode ser um casebre. (Só fonte precisa
        # devolve INDICIO; satélite devolve INDISPONIVEL — a lição §8 'satélite nunca acusa' fica preservada.)
        if vis.get("status") == "INDICIO":
            out = {"status": "INDICIO", "nivel": vis.get("nivel", "MEDIO"),
                   "peso": 12 if vis.get("nivel") == "ALTO" else 9,
                   "estado": f"verificado (imagem de rua: {vis.get('classe', '')})",
                   "evidencia": vis.get("evidencia") or "Foto de rua indica fachada incompatível com a sede.",
                   "sinais": sinais}
            cache[chave] = {**out, "_ts": time.time()}
            _salva_cache()
            return out

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
