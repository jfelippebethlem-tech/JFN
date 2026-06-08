# -*- coding: utf-8 -*-
"""Enriquecedor OCCRP Aleph — JFN 2.0, Onda 12. Follow-the-money cross-jurisdição.

API hospedada gratuita (conta OCCRP — grátis p/ sociedade civil/pesquisadores): 1B+ registros
(empresas, sanções, vazamentos, registros judiciais de 180+ países; modelo FollowTheMoney).
Decisão do dono (2026-06-08): usar Aleph **via API** (a versão a evitar é só a self-host pesada).
SEM auto-hospedar. Requer ALEPH_API_KEY (grátis, em aleph.occrp.org → Settings → API key).

Honesto: sem chave → INDISPONÍVEL; sem match → vazio; nunca fabrica achado. Devolve o link da UI
de cada entidade para registro no dossiê (o achado é um indício a confirmar na fonte).

⚠️ OPSEC: consultas ao Aleph são logadas pelo provedor — usar só com finalidade fiscalizatória legítima.
"""
from __future__ import annotations

import os

import httpx

_BASE = "https://aleph.occrp.org/api/2"
_UI = "https://aleph.occrp.org/entities"


def buscar(nome_ou_cnpj: str, limite: int = 5) -> dict:
    """Busca entidades no Aleph. {ok, alvo, total, matches[{nome,schema,colecao,paises,link}]} |
    INDISPONÍVEL (sem chave). Nunca fabrica."""
    alvo = (nome_ou_cnpj or "").strip()
    if not alvo:
        return {"ok": False, "erro": "informe nome/CNPJ"}
    key = (os.environ.get("ALEPH_API_KEY") or "").strip()
    if not key:
        return {"ok": True, "alvo": alvo, "total": None, "matches": [],
                "_nota": "INDISPONÍVEL: defina ALEPH_API_KEY (grátis em aleph.occrp.org → Settings → API key) "
                         "para cruzar empresas/sanções/vazamentos no OCCRP Aleph. Nada foi fabricado.",
                "_fonte": "OCCRP Aleph API"}
    try:
        r = httpx.get(f"{_BASE}/entities", params={"q": alvo, "limit": limite},
                      headers={"Authorization": f"ApiKey {key}", "User-Agent": "JFN/2.0"}, timeout=25)
        if r.status_code != 200:
            return {"ok": False, "erro": f"Aleph HTTP {r.status_code}"}
        data = r.json() or {}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": f"Aleph: {str(e)[:80]}"}

    res = data.get("results", []) or []
    total = (data.get("total") or {})
    total_n = total.get("value") if isinstance(total, dict) else total
    matches = []
    for it in res:
        props = it.get("properties", {}) or {}
        nomes = props.get("name") or [it.get("caption")]
        paises = props.get("country") or props.get("jurisdiction") or []
        col = (it.get("collection") or {}).get("label") or ""
        eid = it.get("id") or ""
        matches.append({"nome": (nomes or [None])[0], "schema": it.get("schema"),
                        "colecao": col, "paises": paises,
                        "link": f"{_UI}/{eid}" if eid else None})
    return {"ok": True, "alvo": alvo, "total": total_n, "matches": matches,
            "_fonte": "OCCRP Aleph API (uso fiscalizatório)",
            "_nota": "Indício a confirmar na fonte (link da entidade). Consultas são logadas pelo provedor (OPSEC)."}
