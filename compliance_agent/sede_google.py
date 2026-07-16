#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sede_google — verifica a REALIDADE da sede de um fornecedor via 3 APIs do Google (free tier), HONESTO.

Substitui a verificação por Nominatim (que caía em cidade errada e gerava INDÍCIO falso — ver lição §8 e a
auditoria 2026-06-13: 62 INDÍCIO eram Min. da Fazenda, Praça dos Três Poderes etc.). Cada API tem **cota
própria 9999/31d** (free tier; pedido do dono) — guard cliente em disco, espelhando o do Street View.

Sinais coletados (cada um é INDÍCIO, nunca acusação — corroboração ≥2 no motor de DD):
  • **Geocoding** → coord do prédio + `location_type` (ROOFTOP/RANGE_INTERPOLATED=preciso; GEOMETRIC_CENTER=
    aproximado; APPROXIMATE/sem-resultado=não fixou — CUIDADO: rodovia/"S/N"/prédio público dão isso e NÃO são
    fachada).
  • **Address Validation** → `addressComplete`, granularidade, residencial?, ação sugerida (FIX/CONFIRM = ruim).
  • **Places (New)** → existe NEGÓCIO OPERANTE registrado? em que endereço? (ausência num CNPJ que recebeu
    muito = indício de fachada; negócio operante na sede declarada = AFASTA).

LGPD/base legal: fiscalização legítima (Dep. Estadual). Tier p/ caber no free tier: Geocoding em todos;
Address Validation + Places só nos SUSPEITOS (residencial/impreciso/alto-R$).
"""
from __future__ import annotations

import json as _json
import os
import re as _re
import time as _time
import unicodedata as _ud
from pathlib import Path

_QUOTA_DIR = Path("data")
_JANELA = 31 * 86400  # 31 dias


def _gkey() -> str:
    return (os.environ.get("GOOGLE_MAPS_KEY", "") or os.environ.get("STREETVIEW_KEY", "")).strip()


def _norm(s: str) -> str:
    s = (s or "").upper()
    s = "".join(c for c in _ud.normalize("NFD", s) if _ud.category(c) != "Mn")
    return _re.sub(r"\s+", " ", s).strip()


def cep_de(cep: str) -> str:
    """CEP só dígitos (8) ou ''."""
    d = _re.sub(r"[^0-9]", "", str(cep or ""))
    return d[:8] if len(d) >= 8 else ""


# Marcadores fortes de ENTE PÚBLICO / autarquia / concessionária — para DEPRIORIZAR no sweep.
# Sede de fundo municipal, secretaria ou concessionária NÃO é sinal de "fachada" (presunção de regularidade),
# então as PJs PRIVADAS de alto valor vão primeiro na fila de cota (a cota grátis é escassa). Heurística por
# razão social, CONSERVADORA: na dúvida NÃO marca como público, p/ não despriorizar uma privada por engano.
_PUBLICO_RE = _re.compile(
    r"\b(FUNDO|FUNDACAO|PREFEITURA|MUNICIPIO|SECRETARIA|GOVERNO|AUTARQUIA|"
    r"CAMARA\s+MUNICIPAL|ASSEMBLEIA\s+LEGISLATIVA|TRIBUNAL|DEFENSORIA|MINISTERIO\s+PUBLICO|"
    r"ESTADO\s+DO\s+RIO|DEPARTAMENTO\s+DE\s+ESTRADAS|"
    r"LIGHT\s+SERVICOS|CEDAE|COMLURB|CONCESSIONARIA|CONCESSAO|CONCESSOES|ENEL|AGUAS\s+D[OE])\b",
    _re.IGNORECASE)


def e_ente_publico(razao: str) -> bool:
    """True se a razão social parece ente público/autarquia/concessionária (heurística conservadora —
    usada só para ORDENAR a fila do sweep, nunca para excluir; ente público fica por último na cota)."""
    return bool(_PUBLICO_RE.search(razao or ""))


def predio_key(endereco: str, cep: str) -> str:
    """Chave de PRÉDIO p/ dedup: logradouro + 1º número + CEP (ignora sala/apto/bloco). Mesmo prédio = 1
    requisição; todas as empresas nele herdam o resultado (economia de cota — pedido do dono)."""
    e = _norm(endereco)
    cepd = cep_de(cep)
    m = _re.search(r"^(.*?)(\d{1,6})", e)
    if m:
        log = _re.sub(r"[,]", " ", m.group(1)).strip()
        num = m.group(2)
    else:
        log, num = _re.sub(r"[,]", " ", e).strip(), ""
    return f"{_re.sub(r'  +', ' ', log).strip()}|{num}|{cepd}"


def _consome_cota(api: str, default_max: int = 9999) -> bool:
    """True se ainda há cota da `api` na janela de 31 dias; consome 1. Teto via env `<API>_MAX_31D`.
    Guard cliente p/ NUNCA passar do free tier (cada API conta separado)."""
    env = {"geocoding": "GEOCODING_MAX_31D", "addressvalidation": "ADDRVAL_MAX_31D",
           "places": "PLACES_MAX_31D"}.get(api, api.upper() + "_MAX_31D")
    try:
        maxn = int(os.environ.get(env, str(default_max)))
    except Exception:
        maxn = default_max
    f = _QUOTA_DIR / f"quota_{api}.json"
    try:
        st = _json.loads(f.read_text("utf-8")) if f.exists() else {}
    except Exception:
        st = {}
    now = _time.time()
    if not st.get("janela_inicio") or (now - st["janela_inicio"]) > _JANELA:
        st = {"janela_inicio": now, "count": 0}
    if st.get("count", 0) >= maxn:
        return False
    st["count"] = st.get("count", 0) + 1
    try:
        _QUOTA_DIR.mkdir(exist_ok=True)
        f.write_text(_json.dumps(st), "utf-8")
    except (OSError, TypeError):
        pass
    return True


def cota_restante(api: str, default_max: int = 9999) -> int:
    """Quanto resta da cota da `api` na janela atual (sem consumir)."""
    env = {"geocoding": "GEOCODING_MAX_31D", "addressvalidation": "ADDRVAL_MAX_31D",
           "places": "PLACES_MAX_31D"}.get(api, api.upper() + "_MAX_31D")
    try:
        maxn = int(os.environ.get(env, str(default_max)))
    except Exception:
        maxn = default_max
    f = _QUOTA_DIR / f"quota_{api}.json"
    try:
        st = _json.loads(f.read_text("utf-8")) if f.exists() else {}
    except Exception:
        st = {}
    if not st.get("janela_inicio") or (_time.time() - st["janela_inicio"]) > _JANELA:
        return maxn
    return max(0, maxn - int(st.get("count", 0)))


# ───────────────────────────── coletores (cada um quota-guarded + degrada honesto) ─────────────────────────────
def geocodificar(endereco: str) -> dict | None:
    """Geocoding API → {lat,lon,location_type,municipio,formatted} ou None. Consome 1 cota geocoding."""
    import httpx
    gkey = _gkey()
    if not gkey or not endereco.strip() or not _consome_cota("geocoding"):
        return None
    try:
        r = httpx.get("https://maps.googleapis.com/maps/api/geocode/json",
                      params={"address": f"{endereco}, Brasil", "key": gkey, "region": "br"},
                      timeout=20).json()
    except Exception:  # noqa: BLE001
        return None
    if r.get("status") != "OK" or not r.get("results"):
        return {"location_type": "", "lat": None, "lon": None, "municipio": "", "formatted": "",
                "status": r.get("status", "")}  # sem resultado é um SINAL (não é erro)
    g = r["results"][0]
    loc = g["geometry"]["location"]
    mun = next((c["long_name"] for c in g.get("address_components", [])
                if "administrative_area_level_2" in c.get("types", [])), "")
    return {"lat": loc["lat"], "lon": loc["lng"], "location_type": g["geometry"].get("location_type", ""),
            "municipio": mun, "formatted": g.get("formatted_address", ""), "status": "OK"}


def validar(endereco: str) -> dict | None:
    """Address Validation API → {completo,validacao,geocode,residencial,acao} ou None. Consome 1 cota."""
    import httpx
    gkey = _gkey()
    if not gkey or not endereco.strip() or not _consome_cota("addressvalidation"):
        return None
    try:
        r = httpx.post(f"https://addressvalidation.googleapis.com/v1:validateAddress?key={gkey}",
                       json={"address": {"regionCode": "BR", "addressLines": [endereco]}}, timeout=20)
    except Exception:  # noqa: BLE001
        return None
    if r.status_code != 200:
        return None
    res = r.json().get("result", {})
    v = res.get("verdict", {})
    meta = res.get("metadata", {})
    return {"completo": bool(v.get("addressComplete")),
            "validacao": v.get("validationGranularity", ""),
            "geocode": v.get("geocodeGranularity", ""),
            "input": v.get("inputGranularity", ""),
            "acao": v.get("possibleNextAction", ""),
            "residencial": meta.get("residential"),  # True/False/None
            "negocio": meta.get("business"),
            "po_box": meta.get("poBox")}


def buscar_negocio(razao: str, endereco: str, municipio: str = "") -> dict | None:
    """Places API (New) Text Search → negócio operante registrado? {achou,status,nome,endereco,tipos,bate_mun}
    ou None. Consome 1 cota places."""
    import httpx
    gkey = _gkey()
    if not gkey or not _consome_cota("places"):
        return None
    query = " ".join(p for p in [razao, endereco] if p).strip()
    if not query:
        return None
    hdr = {"Content-Type": "application/json", "X-Goog-Api-Key": gkey,
           "X-Goog-FieldMask": "places.displayName,places.businessStatus,places.formattedAddress,places.types"}
    try:
        r = httpx.post("https://places.googleapis.com/v1/places:searchText", headers=hdr,
                       json={"textQuery": query, "languageCode": "pt-BR", "maxResultCount": 3}, timeout=20)
    except Exception:  # noqa: BLE001
        return None
    if r.status_code != 200:
        return None
    places = r.json().get("places", [])
    if not places:
        return {"achou": False, "status": "", "nome": "", "endereco": "", "tipos": [],
                "bate_mun": None, "bate_nome": None}
    p = places[0]
    fa = p.get("formattedAddress", "")
    nome = (p.get("displayName") or {}).get("text", "")
    bate = (_norm(municipio) in _norm(fa)) if municipio else None
    return {"achou": True, "status": p.get("businessStatus", ""), "nome": nome,
            "endereco": fa, "tipos": p.get("types", []), "bate_mun": bate,
            "bate_nome": _nomes_batem(razao, nome)}


# tokens societários ignorados na comparação de nome (não distinguem empresa)
_STOP = {"LTDA", "SA", "S", "A", "ME", "EPP", "EIRELI", "CIA", "COMPANHIA", "E", "DE", "DA", "DO", "DOS",
         "DAS", "EM", "COMERCIO", "SERVICOS", "SERVICO", "INDUSTRIA", "COM", "IND", "LTD", "GROUP", "GRUPO"}


def _nomes_batem(razao: str, nome_google: str) -> bool:
    """True se a razão social e o nome do negócio no Google compartilham um token SIGNIFICATIVO (anti
    'achou um posto de gasolina no endereço da NRTT'). Conservador: exige ≥1 palavra não-genérica em comum."""
    ta = {w for w in _norm(razao).split() if len(w) >= 3 and w not in _STOP}
    tb = {w for w in _norm(nome_google).split() if len(w) >= 3 and w not in _STOP}
    return bool(ta & tb)


# ───────────────────────────── orquestração: coleta os sinais (DD interpreta) ─────────────────────────────
def coletar_sinais(razao: str, endereco: str, municipio: str = "", uf: str = "", cep: str = "", *,
                   com_validacao: bool = True, com_places: bool = True) -> dict:
    """Coleta os sinais Google da sede (cada chamada quota-guarded). NÃO acusa — devolve os sinais crus +
    flags p/ o motor de DD compor o veredito honesto. `com_validacao`/`com_places=False` poupam cota (tier)."""
    from compliance_agent.fachada_doubt import limpa_endereco
    end_full = limpa_endereco(", ".join(p for p in [endereco, municipio, uf, cep] if p))
    sinais: dict = {"endereco_consultado": end_full}
    sinais["geocode"] = geocodificar(end_full)
    sinais["validacao"] = validar(end_full) if com_validacao else None
    sinais["places"] = buscar_negocio(razao, endereco, municipio) if com_places else None
    return sinais


def _moeda(v: float) -> str:
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ 0,00"


def verdict_de_sinais(sinais: dict, total_pago: float = 0.0) -> dict:
    """Compõe um veredito HONESTO dos sinais Google (indício ≠ acusação; corroboração; ausência ≠ prova).

    Regra-mãe: **negócio operante na sede declarada AFASTA** (vence o residencial). Endereço completo+preciso
    afasta inexistência. CUIDADO (lição §8): NÃO afirmar inexistência só por 'não geolocalizou' — exige também
    Address Validation dizer incompleto (rodovia/'S/N'/prédio público dão APPROXIMATE e SÃO reais).
    Retorna {status, nivel, evidencia, pos:[...], neg:[...]}. status: AFASTADO|INDICIO|INDISPONIVEL.
    """
    g = sinais.get("geocode") or {}
    v = sinais.get("validacao") or {}
    p = sinais.get("places") or {}
    lt = g.get("location_type") or ""
    completo = v.get("completo")
    val = v.get("validacao") or ""
    resid = v.get("residencial")
    achou = p.get("achou")
    pstatus = p.get("status") or ""
    bate = p.get("bate_mun")
    alto = bool(total_pago and total_pago > 1_000_000)

    bate_nome = p.get("bate_nome")
    pos, neg = [], []
    # negócio operante DA PRÓPRIA EMPRESA na sede (nome bate) → AFASTA. Comércio de TERCEIRO no endereço
    # (nome não bate) NÃO prova a empresa, mas mostra que o endereço é comercial real (não baldio).
    negocio_operante = bool(achou and pstatus == "OPERATIONAL" and bate_nome and bate is not False)
    if negocio_operante:
        pos.append(f"negócio operante da empresa registrado no Google na sede ({(p.get('nome') or '').strip()[:40]})")
    elif achou and bate_nome is False:
        pos.append(f"há comércio de terceiro operante no endereço ({(p.get('nome') or '').strip()[:30]}) — "
                   "endereço comercial real, mas a empresa investigada não foi localizada lá")
    if lt in ("ROOFTOP", "RANGE_INTERPOLATED"):  # o Google achou o PRÉDIO no nº → endereço existe fisicamente
        pos.append("endereço existe fisicamente (geocode preciso no número" +
                   (", confirmado pela Address Validation)" if completo else ")"))
    if resid is True:
        neg.append("Address Validation classifica o endereço como RESIDENCIAL")
    if achou is False and alto:
        neg.append(f"nenhum negócio operante registrado no Google na sede, apesar de {_moeda(total_pago)} recebidos")
    if achou and bate_nome and bate is False:
        neg.append(f"o negócio da empresa no Google fica em município diferente do declarado ({p.get('endereco', '')[:50]})")
    # inexistência só com DUAS evidências (incompleto + não-geolocalizado) — nunca só por 'não achou no mapa'
    if completo is False and lt in ("APPROXIMATE", "") and val in ("OTHER", ""):
        neg.append("endereço não confirmado (incompleto + sem geolocalização) — apurar existência física")

    if negocio_operante:                       # negócio operante na sede vence o residencial
        status, nivel = "AFASTADO", "BAIXO"
    elif pos and not neg:
        status, nivel = "AFASTADO", "BAIXO"
    elif neg:
        status = "INDICIO"
        nivel = "ALTO" if (len(neg) >= 2 and alto) else "MEDIO"
    else:
        status, nivel = "INDISPONIVEL", "—"
    ev = ("; ".join(neg) if neg else "; ".join(pos)) or "sinais insuficientes para verificar a sede"
    return {"status": status, "nivel": nivel, "evidencia": ev[0:1].upper() + ev[1:] + ".", "pos": pos, "neg": neg}
