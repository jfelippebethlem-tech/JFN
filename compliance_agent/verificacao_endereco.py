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


def _fetch_streetview_google(lat: float, lon: float, chave: str) -> bytes | None:
    """Foto de rua (Google Street View Static) do ponto — precisa de chave. JPG ou None."""
    try:
        import httpx
    except Exception:
        return None
    url = ("https://maps.googleapis.com/maps/api/streetview"
           f"?size=640x480&location={lat},{lon}&fov=80&key={chave}")
    try:
        r = httpx.get(url, timeout=20)
        # o Street View devolve uma imagem 'sem cobertura' (cinza) com 200 — filtrar é trabalho do VLM
        return r.content if (r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff") else None
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
    tipo = "satélite (vista aérea do entorno da quadra)" if fonte == "esri" else "foto de rua (Street View)"
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


def classificar_local_por_imagem(lat: float, lon: float, endereco: str = "") -> dict:
    """Resolve um endereço por IMAGEM: Street View (Google, se chave) ou satélite (Esri, grátis) → VLM.

    Retorna {ok, status, nivel, classe, confianca, fonte, evidencia}. status: INDICIO|AFASTADO|INDISPONIVEL.
    HONESTO: o satélite usa coords no nível da rua (±~100m) → veredito do ENTORNO, não do lote exato; baldio/
    rural no entorno de uma fornecedora é indício a apurar (confirmar in loco), não acusação."""
    base = {"ok": False, "status": "INDISPONIVEL", "nivel": "—", "classe": "", "confianca": 0.0,
            "fonte": "", "evidencia": ""}
    if lat is None or lon is None:
        return {**base, "evidencia": "sem coordenadas p/ buscar imagem"}
    gkey = (os.environ.get("GOOGLE_MAPS_KEY", "") or os.environ.get("STREETVIEW_KEY", "")).strip()
    img, fonte = (None, "")
    if gkey:
        img = _fetch_streetview_google(lat, lon, gkey)
        fonte = "streetview"
    if img is None:
        img = _fetch_satelite_esri(lat, lon)
        fonte = "esri"
    if img is None:
        return {**base, "evidencia": "não foi possível obter imagem (Street View/satélite indisponível)"}
    v = _vlm_classificar(img, fonte, endereco)
    if not v.get("ok"):
        return {**base, "fonte": fonte, "evidencia": f"imagem obtida ({fonte}) mas VLM indisponível: {v.get('motivo', '')}"}
    classe, conf, desc = v["classe"], v["confianca"], v.get("descricao", "")
    preciso = fonte == "streetview"  # só o Street View mira o lote; satélite é o ENTORNO (±~100m)
    fonte_lbl = "Google Street View" if preciso else "satélite Esri (entorno da quadra, ±~100m)"

    # ACUSAÇÃO (baldio/barraco/rural) só com fonte PRECISA. Satélite no centroide da rua já classificou
    # o Banco do Brasil como 'barraco' (falso) — imprecisão + alucinação do VLM. Honestidade: não acusar.
    if classe in _CLASSE_INDICIO:
        if preciso:
            return {"ok": True, "status": "INDICIO", "nivel": "ALTO" if conf >= 0.6 else "MEDIO",
                    "classe": classe, "confianca": conf, "fonte": fonte_lbl,
                    "evidencia": (f"Street View classifica a sede como **{classe.replace('_', ' ')}** "
                                  f"(confiança {conf:.0%}): {desc}. Sede de fornecedora do Estado sem edificação "
                                  "compatível com operação é indício de fachada/inexistência — confirmar in loco.")}
        return {**base, "ok": True, "status": "INDISPONIVEL", "classe": classe, "confianca": conf,
                "fonte": fonte_lbl,
                "evidencia": (f"O satélite do entorno SUGERE '{classe.replace('_', ' ')}', mas a coordenada é no "
                              "nível da rua (imprecisa p/ o lote) — NÃO conclusivo (satélite chega a confundir "
                              "prédio com construção precária). Confirmar por Street View (requer GOOGLE_MAPS_KEY) "
                              "ou diligência in loco antes de qualquer conclusão.")}
    if classe == "indeterminado":
        return {**base, "ok": True, "fonte": fonte_lbl, "classe": classe, "confianca": conf,
                "evidencia": f"Análise visual ({fonte_lbl}) inconclusiva: {desc}."}
    # classes EDIFICADAS (casa/prédio/comercial/galpão) → AFASTAR é seguro (falso-negativo é aceitável; nunca acusa)
    return {"ok": True, "status": "AFASTADO", "nivel": "BAIXO", "classe": classe, "confianca": conf,
            "fonte": fonte_lbl,
            "evidencia": (f"Análise visual ({fonte_lbl}) indica área edificada ({classe.replace('_', ' ')}, "
                          f"confiança {conf:.0%}): {desc}. Compatível com sede real — sem indício visual de fachada.")}


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
