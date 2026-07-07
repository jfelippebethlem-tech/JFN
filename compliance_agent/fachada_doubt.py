#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fachada_doubt — quando a verificação de endereço fica em DÚVIDA, pede o olho humano.

A `verificacao_endereco` devolve `INDISPONIVEL` (ou VLM `indeterminado`) quando NÃO consegue
decidir se a sede é **terreno baldio / residência / sede comercial real** — tipicamente porque o
número não geolocaliza (só o logradouro/CEP) ou o satélite/entorno é imreciso. Esses casos NÃO são
"limpo": são **dúvida honesta**. Em vez de chutar, este módulo:

  1. seleciona as dúvidas que MAIS importam (ranqueadas pelo R$ realmente recebido em OB),
  2. busca a **foto Street View** (Google) do ponto — fonte rente ao chão que distingue casebre de prédio,
  3. envia foto + contexto honesto ao Telegram do dono (`tools/doubt_sender_fachada.py`),
  4. registra a **resposta humana** (fachada/real/pular) como VERDADE (`tools/registrar_vereditos_fachada.py`),
     que a DD passa a usar como override (`veredito_humano`).

Captura da resposta SEM brigar com o Yoda: o gateway do Hermes já é o ÚNICO consumidor do `getUpdates`
do bot (um 2º poller = conflito 409, lição §9). Então NÃO pollamos — lemos passivamente o `state.db` do
Hermes (onde toda mensagem do dono é persistida) e casamos um **código curto** impresso na legenda. Zero
edição do Hermes (run.py vendored é reaplicado a cada update), zero 2º bot, zero conflito.

Honestidade (regra-mãe): a dúvida NÃO é acusação; a legenda diz se a coordenada é o número exato ou o
ponto aproximado da rua (±100m); o veredito é do HUMANO, não do modelo.
"""
from __future__ import annotations

import logging
import datetime as dt
import hashlib
import json as _json
import math as _math
import os
import re as _re
import sqlite3
import time as _time
import unicodedata as _ud
from pathlib import Path

_DB = Path(os.environ.get("JFN_DB", "data/compliance.db"))
_HERMES_STATE = Path(os.environ.get("HERMES_STATE_DB", str(Path.home() / ".hermes" / "state.db")))
_CURSOR = Path("data") / ".fachada_veredito_cursor"

# alfabeto base32 sem caracteres ambíguos (0/O/1/I/L) — código fácil de digitar no Telegram
_ALFA = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

_DDL = """
CREATE TABLE IF NOT EXISTS fachada_veredito (
  cnpj           TEXT PRIMARY KEY,
  codigo         TEXT UNIQUE,
  razao          TEXT,
  endereco       TEXT,
  lat            REAL,
  lon            REAL,
  exato          INTEGER,
  total_recebido REAL,
  street_fonte   TEXT,
  message_id     INTEGER,
  enviado_em     TEXT,
  status         TEXT DEFAULT 'pendente',   -- pendente | fachada | real | pular
  veredito_em    TEXT,
  veredito_raw   TEXT
);
"""


logger = logging.getLogger(__name__)


def conectar(db: Path | str | None = None) -> sqlite3.Connection:
    """Conexão com busy_timeout + WAL (lição §8: todo writer concorrente do compliance.db)."""
    con = sqlite3.connect(str(db or _DB), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.row_factory = sqlite3.Row
    return con


def garantir_schema(con: sqlite3.Connection) -> None:
    con.executescript(_DDL)
    con.commit()


def codigo_de(cnpj: str, comprimento: int = 5) -> str:
    """Código curto determinístico (idempotente/resumível) a partir do CNPJ."""
    h = hashlib.sha1(("fachada:" + str(cnpj)).encode()).digest()
    n = int.from_bytes(h[:8], "big")
    out = []
    for _ in range(comprimento):
        n, r = divmod(n, len(_ALFA))
        out.append(_ALFA[r])
    return "".join(out)


def _moeda(v: float) -> str:
    s = f"{float(v or 0):,.2f}"
    return "R$ " + s.replace(",", "·").replace(".", ",").replace("·", ".")


# Órgãos públicos / bancos / mega-entidades NÃO são fornecedoras sob suspeita de fachada — o ranking por R$
# os traz no topo (Ministério da Fazenda, Banco do Brasil receberam BILHÕES em transferências, não fachada).
# Excluídos por nome (lição do dry-run: foco é a atenção do auditor, não a maior soma).
_BLOCKLIST_NOME = [
    "BANCO%", "%CAIXA ECONOMICA%", "MINISTERIO%", "SECRETARIA%", "PREFEITURA%", "MUNICIPIO DE%",
    "ESTADO DO%", "GOVERNO%", "FUNDO %", "%INSTITUTO NACIONAL%", "UNIVERSIDADE%", "%AUTARQUIA%",
    "TRIBUNAL%", "ASSEMBLEIA%", "CAMARA MUNICIPAL%", "DEFENSORIA%", "PROCURADORIA%", "CORREIOS%",
    "PETROBRAS%", "ELETROBRAS%", "FURNAS%", "DEPARTAMENTO%", "%AGENCIA NACIONAL%", "CONSELHO REGIONAL%",
    "DETRAN%", "%RECEITA FEDERAL%", "INSS%", "%COMPANHIA ESTADUAL%",
]


def _tem_marcador_residencial(endereco: str) -> list[str]:
    """Marcadores residenciais (CASA/APTO/FUNDOS/RESIDENCIAL…) no endereço — perfil clássico de fachada."""
    try:
        from compliance_agent.investigacao_dd import _marcadores_residenciais
        return _marcadores_residenciais(endereco or "")
    except Exception:
        return []


# ───────────────────────────── seleção das dúvidas ─────────────────────────────
def candidatos(con: sqlite3.Connection, limite: int = 15, *, incluir_aproximado: bool = True,
               min_recebido: float = 0.0, so_residencial: bool = True) -> list[dict]:
    """Dúvidas de endereço com PERFIL de fachada, ranqueadas pelo R$ recebido (OB = verdade de pagamento).

    Dúvida = `endereco_verificacao.status='INDISPONIVEL'` ou VLM `visual_classe='indeterminado'`, COM
    coordenada (lat/lon) p/ buscar a foto. Filtros de PRECISÃO (a atenção do auditor é o recurso escasso):
      • exclui órgãos públicos/bancos/mega-entidades (`_BLOCKLIST_NOME`) — não são fornecedoras de fachada;
      • `so_residencial` (default) exige marcador residencial no endereço — o perfil real de fachada
        (empresa que move recurso público sediada em casa/apto/fundos), não um grande empreiteiro com sede real;
      • exclui quem já está em `fachada_veredito`; `incluir_aproximado=False` restringe ao nº exato.
    """
    garantir_schema(con)
    cond_exato = "" if incluir_aproximado else " AND ev.exato = 1 "
    cond_block = "".join(f" AND UPPER(ef.razao) NOT LIKE '{p}' " for p in _BLOCKLIST_NOME)
    # No modo residencial, o filtro (marcador no endereço) roda em Python, então é preciso buscar um conjunto
    # AMPLO de dúvidas (o GROUP BY de 1,1M OBs já é o custo; trazer mais linhas depois é barato) p/ ter recall
    # de fachadas residenciais em toda a faixa de R$, não só as de maior valor. Override por env.
    fetch = int(os.environ.get("FACHADA_FETCH", "12000")) if so_residencial else int(limite)
    sql = f"""
        SELECT ev.cnpj, ev.lat, ev.lon, ev.exato, ev.status, ev.visual_classe, ev.evidencia,
               ef.razao, ef.endereco, ef.municipio, ef.uf, ef.cep,
               ob.total AS total_recebido
        FROM endereco_verificacao ev
        JOIN endereco_fornecedor ef ON ef.cnpj = ev.cnpj
        JOIN (
            SELECT favorecido_cpf AS cnpj, SUM(valor) AS total
            FROM ordens_bancarias
            GROUP BY favorecido_cpf
            HAVING total > ?
        ) ob ON ob.cnpj = ev.cnpj
        WHERE (ev.status = 'INDISPONIVEL' OR ev.visual_classe = 'indeterminado')
          AND ev.lat IS NOT NULL AND ev.lon IS NOT NULL
          AND LENGTH(ev.cnpj) = 14
          {cond_exato}
          {cond_block}
          AND ev.cnpj NOT IN (SELECT cnpj FROM fachada_veredito)
        ORDER BY ob.total DESC
        LIMIT ?
    """
    rows = [dict(r) for r in con.execute(sql, (float(min_recebido), int(fetch))).fetchall()]
    if so_residencial:
        out = []
        for r in rows:
            marcs = _tem_marcador_residencial(r.get("endereco", ""))
            if marcs:
                r["marcadores"] = marcs
                out.append(r)
            if len(out) >= limite:
                break
        return out
    return rows[:limite]


def endereco_completo(cand: dict) -> str:
    """Monta a string de endereço p/ o Street View geocodificar (logradouro+nº, bairro, município, UF, CEP)."""
    cep = str(cand.get("cep") or "").strip()
    cep = f"{cep[:5]}-{cep[5:]}" if len(_digitos(cep)) == 8 else cep
    partes = [str(cand.get("endereco") or "").strip(),
              str(cand.get("municipio") or "").strip(),
              str(cand.get("uf") or "").strip(), cep]
    return ", ".join(p for p in partes if p)


# ───────────────────────────── foto de rua (Street View POR ENDEREÇO) ─────────────────────────────
# LIÇÃO DURA (2026-06-13, lote 1): a coord guardada em `endereco_verificacao` é `exato=0` (Nominatim coarse)
# e CAI EM CIDADE ERRADA (Araçatuba no lugar de SP; Guapimirim no lugar de Freguesia) → a foto não batia o
# endereço. Conserto: passar o ENDEREÇO COMPLETO como string ao Street View, que geocodifica internamente
# (funciona mesmo com a Geocoding API negada na chave) e devolve a coord/pano CORRETOS. Não usar a coord podre.
def _digitos(s) -> str:
    import re
    return re.sub(r"\D", "", str(s or ""))


def _gkey() -> str:
    return (os.environ.get("GOOGLE_MAPS_KEY", "") or os.environ.get("STREETVIEW_KEY", "")).strip()


def limpa_endereco(s: str) -> str:
    """Normaliza o endereço p/ o geocoder não se perder (lição: "AVENIDA, ..., Nº2596, BAIRRO" caía em
    GEOMETRIC_CENTER a 2km; limpo → ROOFTOP). Tira "Nº", colapsa vírgulas/espaços duplicados."""
    s = _re.sub(r"\bN[ºo°]\.?\s*", "", s or "", flags=_re.I)
    s = _re.sub(r"\s*,\s*", ", ", s)
    return _re.sub(r"\s+", " ", s).strip(" ,")


# ── Teto de uso da GEOCODING API (9999/31d) — igual ao do Street View, p/ ficar no free tier (pedido do dono) ──
_GEO_QUOTA_FILE = Path("data") / "geocoding_quota.json"
_GEO_QUOTA_JANELA = 31 * 86400


def _geocode_consome_cota() -> bool:
    """True se ainda há cota de Geocoding na janela de 31 dias; consome 1. Teto `GEOCODING_MAX_31D` (9999)."""
    try:
        maxn = int(os.environ.get("GEOCODING_MAX_31D", "9999"))
    except Exception:
        maxn = 9999
    try:
        st = _json.loads(_GEO_QUOTA_FILE.read_text("utf-8")) if _GEO_QUOTA_FILE.exists() else {}
    except Exception:
        st = {}
    now = _time.time()
    ini = st.get("janela_inicio", 0)
    if not ini or (now - ini) > _GEO_QUOTA_JANELA:
        st = {"janela_inicio": now, "count": 0}
    if st.get("count", 0) >= maxn:
        return False
    st["count"] = st.get("count", 0) + 1
    try:
        _GEO_QUOTA_FILE.parent.mkdir(exist_ok=True)
        _GEO_QUOTA_FILE.write_text(_json.dumps(st), "utf-8")
    except Exception as exc:
        logger.warning("contador de cota de geocoding NÃO persistiu (guarda de custo furada): %s", exc)
    return True


def _pano_meta(location: str) -> dict | None:
    """Metadata GRATUITO do Street View (cobertura + coord/data do pano) num ponto 'lat,lng' ou endereço."""
    import httpx
    gkey = _gkey()
    if not gkey:
        return None
    try:
        m = httpx.get("https://maps.googleapis.com/maps/api/streetview/metadata",
                      params={"location": location, "key": gkey}, timeout=20).json()
    except Exception:  # noqa: BLE001
        return None
    if m.get("status") != "OK" or not m.get("location"):
        return None
    return {"lat": m["location"]["lat"], "lon": m["location"]["lng"], "date": m.get("date", "")}


def coord_do_endereco(endereco: str) -> tuple[dict | None, str]:
    """Coord do pano via metadata GRATUITO (Google resolve o nº internamente). Devolve ({lat,lon,date}, "")
    ou (None, motivo). Metadata NÃO consome cota/cobrança (doc Google)."""
    if not _gkey():
        return None, "sem GOOGLE_MAPS_KEY"
    if not endereco.strip():
        return None, "endereço vazio"
    p = _pano_meta(f"{limpa_endereco(endereco)}, Brasil")
    return (p, "") if p else (None, "sem cobertura Street View no endereço")


def _geocode_predio(endereco: str) -> dict | None:
    """Coord do PRÉDIO via Geocoding API (≠ pano) p/ ancorar a foto e calcular o heading. Quota-guarded
    (9999/31d). Geocoding negada/cota/erro → None (degrada: foto sem heading).
    Devolve {lat,lon,location_type} (ROOFTOP/RANGE_INTERPOLATED/GEOMETRIC_CENTER/APPROXIMATE)."""
    import httpx
    gkey = _gkey()
    if not gkey or not endereco.strip() or not _geocode_consome_cota():
        return None
    try:
        r = httpx.get("https://maps.googleapis.com/maps/api/geocode/json",
                      params={"address": f"{limpa_endereco(endereco)}, Brasil", "key": gkey, "region": "br"},
                      timeout=20).json()
    except Exception:  # noqa: BLE001
        return None
    if r.get("status") != "OK" or not r.get("results"):
        return None
    g = r["results"][0]
    loc = g["geometry"]["location"]
    return {"lat": loc["lat"], "lon": loc["lng"],
            "location_type": g["geometry"].get("location_type", "")}


def _bearing(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """Rumo (compass bearing, 0-360) de A→B — heading p/ a câmera olhar do pano (A) para o prédio (B)."""
    p1, p2 = _math.radians(a_lat), _math.radians(b_lat)
    dl = _math.radians(b_lon - a_lon)
    y = _math.sin(dl) * _math.cos(p2)
    x = _math.cos(p1) * _math.sin(p2) - _math.sin(p1) * _math.cos(p2) * _math.cos(dl)
    return (_math.degrees(_math.atan2(y, x)) + 360) % 360


def _dist_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """Distância em metros (haversine) — guarda do heading (pano longe do prédio = rumo não confiável)."""
    p1, p2 = _math.radians(a_lat), _math.radians(b_lat)
    dp, dl = _math.radians(b_lat - a_lat), _math.radians(b_lon - a_lon)
    h = _math.sin(dp / 2) ** 2 + _math.cos(p1) * _math.cos(p2) * _math.sin(dl / 2) ** 2
    return 2 * 6371000 * _math.asin(min(1, _math.sqrt(h)))


def foto_rua(endereco: str) -> tuple[bytes | None, str, dict]:
    """Foto Street View da SEDE (API Static), ANCORADA na coord do prédio (Geocoding) p/ a câmera mirar a
    fachada. Fluxo: limpa endereço → geocoda o prédio → metadata no ponto do prédio → heading pano→prédio →
    foto. Sem Geocoding (negada/cota) → metadata pelo endereço, heading padrão (degrada honesto).

    Devolve (bytes_jpeg, fonte, info{lat,lon,date,heading?,geocode?}) ou (None, motivo, {}).
    """
    import httpx
    from compliance_agent import verificacao_endereco as ve
    gkey = _gkey()
    if not gkey:
        return None, "sem GOOGLE_MAPS_KEY", {}
    end = limpa_endereco(endereco)
    if not end:
        return None, "endereço vazio", {}

    predio = _geocode_predio(end)   # coord do prédio (só com Geocoding ligada + cota)
    anchor = None
    if predio and predio.get("location_type") in ("ROOFTOP", "RANGE_INTERPOLATED", "GEOMETRIC_CENTER"):
        anchor = (predio["lat"], predio["lon"])
        pano = _pano_meta(f"{anchor[0]},{anchor[1]}")     # pano mais perto do prédio
    else:
        pano = _pano_meta(f"{end}, Brasil")               # fallback: pano pelo endereço
    if not pano:
        return None, "sem cobertura Street View no endereço", {}
    if not ve._streetview_consome_cota():  # respeita o teto de requisições PAGAS (imagem)
        return None, "cota Street View esgotada", {}

    params = {"size": "640x640", "fov": "80", "pitch": "0", "source": "outdoor", "key": gkey}
    if anchor:
        info = {"lat": anchor[0], "lon": anchor[1], "date": pano.get("date", "")}
        params["location"] = f"{anchor[0]},{anchor[1]}"
        # heading só se o pano está PERTO do prédio (rumo confiável); senão deixa o padrão
        if _dist_m(pano["lat"], pano["lon"], anchor[0], anchor[1]) <= 120:
            heading = _bearing(pano["lat"], pano["lon"], anchor[0], anchor[1])
            params["heading"] = f"{heading:.0f}"
            params["fov"] = "90"
            info["heading"] = round(heading)
        info["geocode"] = predio.get("location_type", "")
    else:
        info = {**pano}
        params["location"] = f"{end}, Brasil"
    try:
        r = httpx.get("https://maps.googleapis.com/maps/api/streetview", params=params, timeout=25)
    except Exception as e:  # noqa: BLE001
        return None, f"erro download: {str(e)[:40]}", {}
    if r.status_code != 200 or r.content[:3] != b"\xff\xd8\xff":
        return None, f"download falhou (HTTP {r.status_code})", {}
    return r.content, "streetview", info


# ───────────────────────────── legenda honesta ─────────────────────────────
def legenda(cand: dict, codigo: str, fonte: str, info: dict | None = None) -> str:
    info = info or {}
    end = ", ".join(p for p in [str(cand.get("endereco") or "").strip(),
                                str(cand.get("municipio") or "").strip(),
                                str(cand.get("uf") or "").strip()] if p)
    data = str(info.get("date") or "").strip()
    lat, lon = info.get("lat"), info.get("lon")
    mapa = f"https://www.google.com/maps?q=&layer=c&cbll={lat},{lon}" if lat and lon else ""
    foto_ln = "📷 Google Street View do endereço" + (f" (pano {data})" if data else "")
    foto_ln += f"\n🔗 conferir no mapa: {mapa}" if mapa else ""
    marcs = cand.get("marcadores") or []
    linha_marc = f"⚠ Marcador residencial no endereço: {', '.join(marcs)}\n" if marcs else ""
    return (
        f"🕵️ DÚVIDA DE FACHADA — preciso do seu olho\n"
        f"Empresa: {cand.get('razao') or '—'}\n"
        f"CNPJ: {cand.get('cnpj')}\n"
        f"Endereço declarado: {end or '—'}\n"
        f"{linha_marc}"
        f"Recebido em OB: {_moeda(cand.get('total_recebido'))}\n"
        f"{foto_ln}\n\n"
        f"A foto bate com sede comercial REAL ou parece FACHADA (casa/baldio/outro)? Responda com:\n"
        f"  {codigo} fachada   (laranja / sede inexistente)\n"
        f"  {codigo} real      (sede legítima)\n"
        f"  {codigo} pular     (foto não confere o endereço / não dá p/ decidir)"
    )


def registrar_envio(con: sqlite3.Connection, cand: dict, codigo: str, fonte: str,
                    message_id: int | None) -> None:
    garantir_schema(con)
    con.execute(
        "INSERT OR REPLACE INTO fachada_veredito "
        "(cnpj, codigo, razao, endereco, lat, lon, exato, total_recebido, street_fonte, "
        " message_id, enviado_em, status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?, 'pendente')",
        (cand["cnpj"], codigo, cand.get("razao"), cand.get("endereco"), cand.get("lat"),
         cand.get("lon"), 1 if cand.get("exato") else 0, cand.get("total_recebido"),
         fonte, message_id, dt.datetime.now().isoformat(timespec="seconds")))
    con.commit()


# ───────────────────────────── captura passiva do veredito (state.db do Hermes) ─────────────────────────────
# O dono responde no Telegram pelo "responder" (quote) — o state.db guarda `[Replying to: "...CNPJ:<14>..."]`,
# então correlacionamos pela CNPJ do quote (mais robusto que o código curto). O status vem do texto da resposta,
# classificado de forma CONSERVADORA (ordem importa): problema-de-foto/inconclusivo → pular ; depois real ;
# depois indício (residencial/apurar) ; depois fachada. Ambíguo → None (vira 'revisar', NÃO chuta).
# Classificação CONSERVADORA por frases (não keywords cruas — "fachada" aparece em "fachada certa"=real,
# "fachada errada"=foto-ruim, "não é a fachada"=ângulo). ORDEM: (1) problema-de-foto/inconclusivo vence
# (não dá p/ confiar na foto); (2) INDÍCIO — "residencial/merece atenção/indício" é o meio nuançado do dono
# (vem ANTES de real/fachada porque ele costuma hedge: "pode ser legítima, mas é um indício"); (3) real; (4) fachada.
_KW_PULAR = ("angulo", "foto errada", "fotos errada", "fachada errada", "fachadas errada", "endereco errado",
             "foto ta errada", "foto ta no endereco", "veio com a foto", "inconclusiv", "nao da pra saber",
             "nao e a fachada", "nao da pra ver", "sem foto ", "pular", "skip", "nao sei", "indeterm")
_KW_INDICIO = ("residencial", "merece atencao", "indicio", "suspeita", "apurar")
_KW_REAL = ("empresa real", "sede real", "predio comercial", "predio empresarial", "fachada certa",
            "logomarca", "sede legitima", "empresa legitima", "comercial real", "e real ", "eh real",
            "parece real", "loja real")
_KW_FACHADA = ("laranja", "baldio", "inexistente", "e uma casa", "eh uma casa", "casa simples",
               "e fachada", "eh fachada", "uma fachada", "fantasma", " fachada ")
# " fachada " (com espaços, via _norm_txt) é o ÚLTIMO recurso: pega o veredito explícito "fachada" sozinho,
# mas NÃO "fachada certa" (=real) nem "fachada errada"/"nao e a fachada" (=pular), que a ORDEM já capturou antes.


def _norm_txt(s: str) -> str:
    s = (s or "").lower()
    s = "".join(c for c in _ud.normalize("NFD", s) if _ud.category(c) != "Mn")
    return " " + _re.sub(r"\s+", " ", s) + " "   # padding p/ casar "e real " no fim


def classificar_resposta(texto: str) -> str | None:
    """Classifica a resposta livre do dono em fachada|real|indicio|pular, ou None (ambíguo → revisar)."""
    t = _norm_txt(texto)
    if not t.strip():
        return None
    if any(k in t for k in _KW_PULAR):
        return "pular"
    if any(k in t for k in _KW_INDICIO):
        return "indicio"
    if any(k in t for k in _KW_REAL):
        return "real"
    if any(k in t for k in _KW_FACHADA):
        return "fachada"
    return None


def _cnpj_do_quote(texto: str) -> str:
    """CNPJ (14 díg) citado no quote `[Replying to: "...CNPJ: <14>..."]` da resposta, ou ''."""
    m = _re.search(r"CNPJ:\s*(\d{14})", texto or "")
    return m.group(1) if m else ""


def _texto_resposta(content: str) -> str:
    """Remove o quote `[Replying to: ...]`, o prefixo `[J FN id=...]` e anexos → só a resposta do dono."""
    t = _re.sub(r"^\[Replying to:.*?\]\s*", "", content or "", flags=_re.S)
    t = _re.sub(r"^\[J ?FN[^\]]*\]\s*", "", t)
    t = _re.sub(r"\[Image attached.*", "", t, flags=_re.S)
    t = _re.sub(r"\[screenshot\]", "", t)
    return t.strip()


# formato INSTRUÍDO ("<código> fachada|real|indicio|pular") — a palavra é o veredito, casa direta (≠ texto livre,
# onde "fachada" engana em "fachada certa"/"não é a fachada"). Usado SÓ na via do código curto.
_EXPLICITO = {"fachada": "fachada", "laranja": "fachada", "baldio": "fachada", "real": "real",
              "legitima": "real", "legitimo": "real", "indicio": "indicio", "residencial": "indicio",
              "pular": "pular", "skip": "pular"}


def _verdito_explicito(texto: str) -> str | None:
    toks = set(_norm_txt(texto).split())
    for w, st in _EXPLICITO.items():
        if w in toks:
            return st
    return None


def interpretar(texto: str, codigos_pendentes: dict[str, str],
                cnpjs_pendentes: set[str] | None = None) -> list[tuple[str, str, str]]:
    """Extrai vereditos de uma mensagem. Devolve [(cnpj, status, raw)].

    Duas vias: (1) **quote** — CNPJ no `[Replying to: ...]` + status do TEXTO LIVRE (classificador conservador,
    é como o dono responde); (2) **código curto** com a palavra-veredito explícita do formato instruído."""
    achados: list[tuple[str, str, str]] = []
    resp = _texto_resposta(texto)
    raw = resp[:200] or (texto or "")[:200]
    # via quote (CNPJ do `[Replying to: ...]`) — texto livre → classificador conservador
    cnpj_q = _cnpj_do_quote(texto)
    if cnpj_q and (cnpjs_pendentes is None or cnpj_q in cnpjs_pendentes):
        st = classificar_resposta(resp)
        if st:
            achados.append((cnpj_q, st, raw))
            return achados  # uma resposta = um veredito
    # via código curto — formato instruído (palavra explícita), com fallback ao classificador
    for codigo, cnpj in codigos_pendentes.items():
        if not _re.search(rf"(?<![A-Za-z0-9]){_re.escape(codigo)}(?![A-Za-z0-9])", texto or "", _re.IGNORECASE):
            continue
        st = _verdito_explicito(resp or texto) or classificar_resposta(resp or texto)
        if st:
            achados.append((cnpj, st, raw))
            break
    return achados


def _ler_cursor() -> float:
    try:
        return float(_CURSOR.read_text().strip())
    except Exception:
        return 0.0


def _grava_cursor(ts: float) -> None:
    try:
        _CURSOR.parent.mkdir(parents=True, exist_ok=True)
        _CURSOR.write_text(f"{ts:.6f}")
    except Exception as exc:
        logger.warning("cursor não gravado (próxima rodada reprocessa desde o anterior): %s", exc)


def mensagens_novas_telegram(desde_ts: float, state_db: Path | None = None) -> list[tuple[float, str]]:
    """Lê o state.db do Hermes: mensagens do dono (role=user, source telegram) após `desde_ts`.

    Passivo e read-only — NÃO compete com o getUpdates do gateway. Devolve [(timestamp, texto)].
    """
    db = state_db or _HERMES_STATE
    if not Path(db).exists():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        rows = con.execute(
            "SELECT m.timestamp, m.content FROM messages m JOIN sessions s ON s.id = m.session_id "
            "WHERE m.role='user' AND s.source LIKE '%telegram%' AND m.timestamp > ? "
            "ORDER BY m.timestamp ASC", (float(desde_ts),)).fetchall()
    finally:
        con.close()
    out = []
    for ts, content in rows:
        out.append((float(ts), str(content or "")))
    return out


def processar_respostas(con: sqlite3.Connection, *, state_db: Path | None = None,
                        avancar_cursor: bool = True) -> list[dict]:
    """Lê as mensagens novas do dono, casa códigos pendentes e grava o veredito. Idempotente."""
    garantir_schema(con)
    rows_pend = con.execute(
        "SELECT codigo, cnpj, enviado_em FROM fachada_veredito WHERE status='pendente'").fetchall()
    pend = {r["codigo"]: r["cnpj"] for r in rows_pend}
    if not pend:
        return []
    cnpjs_pend = set(pend.values())
    # Para o 3º caminho (resposta SEM quote/código): pendentes do mais RECENTE p/ o mais antigo.
    # O dono costuma responder em texto livre logo abaixo da foto que acabou de receber → casa no último enviado.
    def _ts_env(s):
        try:
            return dt.datetime.fromisoformat(s).timestamp()
        except Exception:
            return 0.0
    pend_por_recencia = sorted(((r["cnpj"], _ts_env(r["enviado_em"])) for r in rows_pend),
                               key=lambda x: x[1], reverse=True)
    desde = _ler_cursor()
    msgs = mensagens_novas_telegram(desde, state_db)
    gravados: list[dict] = []
    maior_ts = desde
    for ts, texto in msgs:
        maior_ts = max(maior_ts, ts)
        vereditos = interpretar(texto, pend, cnpjs_pend)
        if not vereditos:
            # 3º caminho: texto é veredito mas sem quote nem código → casa no pendente MAIS RECENTE
            # (a foto que o dono acabou de ver). Heurística marcada no raw p/ auditabilidade.
            st = classificar_resposta(_texto_resposta(texto) or texto or "")
            if st:
                alvo = next((cnpj for cnpj, _e in pend_por_recencia if cnpj in cnpjs_pend), None)
                if alvo:
                    raw = ("sem-quote(heuristica:mais-recente): "
                           + ((_texto_resposta(texto) or texto or "")[:160]))
                    vereditos = [(alvo, st, raw)]
        for cnpj, status, raw in vereditos:
            cur = con.execute(
                "UPDATE fachada_veredito SET status=?, veredito_em=?, veredito_raw=? "
                "WHERE cnpj=? AND status='pendente'",
                (status, dt.datetime.now().isoformat(timespec="seconds"), raw, cnpj))
            if cur.rowcount:
                gravados.append({"cnpj": cnpj, "status": status, "raw": raw})
                pend.pop(codigo_de(cnpj), None)  # não casar de novo nesta passada
                cnpjs_pend.discard(cnpj)
    con.commit()
    if avancar_cursor and msgs:
        _grava_cursor(maior_ts)
    return gravados


# ───────────────────────────── accessor p/ a DD (override do veredito humano) ─────────────────────────────
def veredito_humano(cnpj: str, db: Path | str | None = None) -> dict | None:
    """Veredito humano já registrado p/ um CNPJ, ou None. Usado pela DD como VERDADE (override).

    Devolve {status: fachada|real|indicio, em, raw} p/ vereditos decididos (não 'pendente'/'pular').
    """
    from compliance_agent.investigacao_dd import _digitos
    c = _digitos(cnpj)
    try:
        con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=10)
    except Exception:
        return None
    try:
        r = con.execute(
            "SELECT status, veredito_em, veredito_raw FROM fachada_veredito "
            "WHERE cnpj=? AND status IN ('fachada','real','indicio')", (c,)).fetchone()
    except Exception:
        return None
    finally:
        con.close()
    if not r:
        return None
    return {"status": r[0], "em": r[1], "raw": r[2]}
