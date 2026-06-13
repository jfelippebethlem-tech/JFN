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

import datetime as dt
import hashlib
import os
import sqlite3
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


# ───────────────────────────── foto de rua (Street View → Mapillary) ─────────────────────────────
def foto_rua(lat: float, lon: float) -> tuple[bytes | None, str]:
    """Foto RENTE AO CHÃO do ponto, priorizando o **Street View** (pedido do dono) e caindo p/ Mapillary.

    NÃO usa satélite: a dúvida é resolvida pelo olho humano e o satélite (entorno ±100m) engana mais do que
    ajuda nessa decisão. Devolve (bytes_jpeg, fonte) ou (None, motivo). Respeita a cota paga do Street View.
    """
    from compliance_agent import verificacao_endereco as ve
    gkey = (os.environ.get("GOOGLE_MAPS_KEY", "") or os.environ.get("STREETVIEW_KEY", "")).strip()
    mly = os.environ.get("MAPILLARY_TOKEN", "").strip()
    if gkey:
        img = ve._fetch_streetview_google(lat, lon, gkey)
        if img:
            return img, "streetview"
    if mly:
        img = ve._fetch_mapillary(lat, lon, mly,
                                  raio_m=float(os.environ.get("MAPILLARY_RAIO_M", "120") or 120))
        if img:
            return img, "mapillary"
    return None, "sem cobertura (Street View/Mapillary)"


# ───────────────────────────── legenda honesta ─────────────────────────────
def legenda(cand: dict, codigo: str, fonte: str) -> str:
    exato = bool(cand.get("exato"))
    coord = ("📍 coordenada do NÚMERO exato" if exato
             else "📍 ponto APROXIMADO da rua (±100m) — o número não geolocaliza")
    fonte_lbl = {"streetview": "Google Street View", "mapillary": "Mapillary (foto de rua)"}.get(fonte, fonte)
    ev = (cand.get("evidencia") or "").strip()
    if len(ev) > 280:
        ev = ev[:277] + "…"
    end = ", ".join(p for p in [str(cand.get("endereco") or "").strip(),
                                str(cand.get("municipio") or "").strip(),
                                str(cand.get("uf") or "").strip()] if p)
    marcs = cand.get("marcadores") or []
    linha_marc = f"⚠ Marcador residencial no endereço: {', '.join(marcs)}\n" if marcs else ""
    return (
        f"🕵️ DÚVIDA DE FACHADA — preciso do seu olho\n"
        f"Empresa: {cand.get('razao') or '—'}\n"
        f"CNPJ: {cand.get('cnpj')}\n"
        f"Endereço declarado: {end or '—'}\n"
        f"{linha_marc}"
        f"Recebido em OB: {_moeda(cand.get('total_recebido'))}\n"
        f"{coord} · foto: {fonte_lbl}\n"
        f"Análise automática (inconclusiva): {ev or '—'}\n\n"
        f"A sede parece REAL ou é FACHADA? Responda aqui com:\n"
        f"  {codigo} fachada   (laranja / sede inexistente)\n"
        f"  {codigo} real      (sede legítima)\n"
        f"  {codigo} pular     (não dá p/ decidir pela foto)"
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
# palavras → status canônico
_FACHADA = ("fachada", "laranja", "inexist", "falsa", "baldio")
_REAL = ("real", "legitim", "legítim", "verdadeir", "sede ok", "ok", "existe", "valida", "válida")
_PULAR = ("pular", "skip", "nao sei", "não sei", "naosei", "duvida", "dúvida", "indeterm")


def interpretar(texto: str, codigos_pendentes: dict[str, str]) -> list[tuple[str, str, str]]:
    """Extrai vereditos de um texto livre. Devolve [(cnpj, status, raw)] p/ cada código reconhecido.

    Casa um código pendente em qualquer posição do texto e olha as palavras vizinhas p/ o status.
    Tolerante a maiúsc/minúsc e a "F7ABC: fachada", "fachada F7ABC", "F7ABC real" etc.
    """
    import re
    t = texto or ""
    achados: list[tuple[str, str, str]] = []
    vistos: set[str] = set()
    low = t.lower()
    for codigo, cnpj in codigos_pendentes.items():
        if codigo in vistos:
            continue
        # o código é case-insensitive; procura como palavra
        if not re.search(rf"(?<![A-Za-z0-9]){re.escape(codigo)}(?![A-Za-z0-9])", t, re.IGNORECASE):
            continue
        if any(w in low for w in _FACHADA):
            status = "fachada"
        elif any(w in low for w in _PULAR):
            status = "pular"
        elif any(w in low for w in _REAL):
            status = "real"
        else:
            continue  # código citado mas sem veredito claro → ignora (não chuta)
        achados.append((cnpj, status, t.strip()[:200]))
        vistos.add(codigo)
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
    except Exception:
        pass


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
    pend = {r["codigo"]: r["cnpj"] for r in
            con.execute("SELECT codigo, cnpj FROM fachada_veredito WHERE status='pendente'")}
    if not pend:
        return []
    desde = _ler_cursor()
    msgs = mensagens_novas_telegram(desde, state_db)
    gravados: list[dict] = []
    maior_ts = desde
    for ts, texto in msgs:
        maior_ts = max(maior_ts, ts)
        for cnpj, status, raw in interpretar(texto, pend):
            cur = con.execute(
                "UPDATE fachada_veredito SET status=?, veredito_em=?, veredito_raw=? "
                "WHERE cnpj=? AND status='pendente'",
                (status, dt.datetime.now().isoformat(timespec="seconds"), raw, cnpj))
            if cur.rowcount:
                gravados.append({"cnpj": cnpj, "status": status, "raw": raw})
                pend.pop(codigo_de(cnpj), None)  # não casar de novo nesta passada
    con.commit()
    if avancar_cursor and msgs:
        _grava_cursor(maior_ts)
    return gravados


# ───────────────────────────── accessor p/ a DD (override do veredito humano) ─────────────────────────────
def veredito_humano(cnpj: str, db: Path | str | None = None) -> dict | None:
    """Veredito humano já registrado p/ um CNPJ, ou None. Usado pela DD como VERDADE (override).

    Devolve {status: fachada|real|pular, em, raw} apenas p/ vereditos decididos (não 'pendente'/'pular').
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
            "WHERE cnpj=? AND status IN ('fachada','real')", (c,)).fetchone()
    except Exception:
        return None
    finally:
        con.close()
    if not r:
        return None
    return {"status": r[0], "em": r[1], "raw": r[2]}
