# -*- coding: utf-8 -*-
"""Âncora de mercado — Painel de Preços via API pública de dados abertos.

O front paineldeprecos.planejamento.gov.br dá 403 (WAF); o acesso público é
dadosabertos.compras.gov.br. Cadeia: descrição → PDM (nomePdm) → classe →
item (CATMAT) → preço unitário. Cache 30d por CATMAT (preco_referencia_cache).
Degrada honesto: sem CATMAT confiável → {disponivel: False} (nunca inventa preço).
"""
from __future__ import annotations

import statistics
import unicodedata

import httpx

BASE = "https://dadosabertos.compras.gov.br"
_UA = {"User-Agent": "JFN-Compliance/2.0"}
_TIMEOUT = 30


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def _get(path: str, params: dict) -> dict | None:
    try:
        r = httpx.get(f"{BASE}{path}", params=params, headers=_UA, timeout=_TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def catmat_por_descricao(desc: str, limite: int = 5) -> list[dict]:
    """PDM por palavra-chave → classe → itens (CATMAT). Ranqueia por overlap de tokens."""
    kw = _norm(desc).split()
    if not kw:
        return []
    pdm = _get("/modulo-material/3_consultarPdmMaterial",
               {"pagina": 1, "tamanhoPagina": 10, "nomePdm": kw[0]})
    classes = {p.get("codigoClasse") for p in (pdm or {}).get("resultado", []) if p.get("codigoClasse")}
    itens = []
    for cl in list(classes)[:2]:
        it = _get("/modulo-material/4_consultarItemMaterial",
                  {"pagina": 1, "tamanhoPagina": 50, "codigoClasse": cl})
        for x in (it or {}).get("resultado", []):
            d = _norm(x.get("descricaoItem") or "")
            score = sum(1 for t in kw if t in d)
            if score:
                itens.append({"codigo": str(x.get("codigoItem")), "nome": x.get("descricaoItem"),
                              "score": score})
    itens.sort(key=lambda i: -i["score"])
    return itens[:limite]


def _mediana_precos(payload: dict) -> dict:
    precos = [x.get("precoUnitario") for x in (payload or {}).get("resultado", []) if x.get("precoUnitario")]
    if not precos:
        return {"disponivel": False, "n": 0}
    return {"disponivel": True, "n": len(precos), "mediana": statistics.median(precos),
            "minimo": min(precos), "maximo": max(precos)}


def preco_referencia(catmat: str, con=None) -> dict:
    """Preço de mercado por CATMAT, com cache 30d. Síncrono (httpx.get)."""
    if con is not None:
        row = con.execute(
            "select mediana,n,minimo,maximo, julianday('now')-julianday(atualizado_em) "
            "from preco_referencia_cache where catmat=?", (catmat,)).fetchone()
        if row and row[4] is not None and row[4] < 30:
            return {"disponivel": True, "mediana": row[0], "n": row[1],
                    "minimo": row[2], "maximo": row[3]}
    payload = _get("/modulo-pesquisa-preco/1_consultarMaterial",
                   {"pagina": 1, "tamanhoPagina": 50, "codigoItemCatalogo": catmat})
    r = _mediana_precos(payload or {})
    if con is not None and r.get("disponivel"):
        con.execute(
            """INSERT INTO preco_referencia_cache (catmat, mediana, n, minimo, maximo, atualizado_em)
               VALUES (?,?,?,?,?, datetime('now'))
               ON CONFLICT(catmat) DO UPDATE SET mediana=excluded.mediana, n=excluded.n,
                 minimo=excluded.minimo, maximo=excluded.maximo, atualizado_em=datetime('now')""",
            (catmat, r["mediana"], r["n"], r["minimo"], r["maximo"]))
        con.commit()
    return r
