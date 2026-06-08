# -*- coding: utf-8 -*-
"""Enriquecedor OpenSanctions — JFN 2.0, Onda 12. Sanções + PEP (pessoa politicamente exposta).

API hospedada gratuita (uso não comercial) — entra na seção "listas restritivas" e no score, ao
lado de CEIS/CNEP. SEM auto-hospedar (decisão do dono). Requer OPENSANCTIONS_API_KEY (grátis p/
uso não comercial). Honesto: sem chave ou sem match → INDISPONÍVEL/limpo; nunca fabrica sanção.
"""
from __future__ import annotations

import os

import httpx

_BASE = "https://api.opensanctions.org"


def checar(nome_ou_cnpj: str) -> dict:
    """Screening de sanções/PEP. {ok, alvo, sancionado, pep, matches[]} | INDISPONÍVEL (sem chave)."""
    alvo = (nome_ou_cnpj or "").strip()
    if not alvo:
        return {"ok": False, "erro": "informe nome/CNPJ"}
    key = (os.environ.get("OPENSANCTIONS_API_KEY") or "").strip()
    if not key:
        return {"ok": True, "alvo": alvo, "sancionado": None, "pep": None, "matches": [],
                "_nota": "INDISPONÍVEL: defina OPENSANCTIONS_API_KEY (grátis p/ uso não comercial em "
                         "opensanctions.org) para checar sanções/PEP. Nada foi fabricado.",
                "_fonte": "OpenSanctions API"}
    try:
        r = httpx.get(f"{_BASE}/search/default", params={"q": alvo, "limit": 5},
                      headers={"Authorization": f"ApiKey {key}", "User-Agent": "JFN/2.0"}, timeout=25)
        if r.status_code != 200:
            return {"ok": False, "erro": f"OpenSanctions HTTP {r.status_code}"}
        res = (r.json() or {}).get("results", []) or []
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": f"OpenSanctions: {str(e)[:80]}"}

    matches = []
    sancionado = pep = False
    for it in res:
        topics = (it.get("properties", {}) or {}).get("topics", []) or []
        is_san = any("sanction" in str(t) for t in topics)
        is_pep = any("pep" in str(t) or "role.pep" in str(t) for t in topics)
        sancionado = sancionado or is_san
        pep = pep or is_pep
        matches.append({"nome": it.get("caption"), "schema": it.get("schema"),
                        "topics": topics, "score": it.get("score")})
    return {"ok": True, "alvo": alvo, "sancionado": sancionado, "pep": pep, "matches": matches,
            "_fonte": "OpenSanctions API (uso não comercial)",
            "_nota": "Indício de sanção/PEP a confirmar na fonte; entra no score ao lado de CEIS/CNEP."}
