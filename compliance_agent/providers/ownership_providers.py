# -*- coding: utf-8 -*-
"""Ownership internacional / cross-jurisdição — GLEIF (LEI + relações de controle), sem chave.

Quando a chave do OpenCorporates sair, basta adicionar uma classe OpenCorporates(funcao='ownership')
e registrá-la no __init__ — sem tocar nas rotas (critério de aceite #7 do spec)."""
from __future__ import annotations

import os

import httpx

from .base import RateLimiter, Resultado, agora_iso

_H = {"Accept": "application/vnd.api+json"}


class GLEIF:
    id = "gleif"
    funcao = "ownership"

    def __init__(self):
        self._rl = RateLimiter(5)

    def disponivel(self) -> bool:
        return True

    def consultar(self, *, nome: str | None = None, lei: str | None = None, **_) -> Resultado:
        self._rl.aguardar()
        try:
            if lei:
                r = httpx.get(f"https://api.gleif.org/api/v1/lei-records/{lei}", headers=_H, timeout=20)
            elif nome:
                r = httpx.get("https://api.gleif.org/api/v1/lei-records",
                              params={"filter[entity.legalName]": nome, "page[size]": 5},
                              headers=_H, timeout=20)
            else:
                return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", "sem 'nome'/'lei'")
            if r.status_code == 200:
                return Resultado(True, r.json().get("data"), self.id, agora_iso())
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", f"HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", str(e)[:80])


class OpenCorporates:
    """Vínculos societários cross-jurisdição (170+ jurisdições). Key-gated (free permitted-user):
    OPENCORPORATES_API_TOKEN. Sem token → INDISPONIVEL honesto (nunca fabrica). Entra como mais um
    backend de ownership; o fallback do registry já cobre o BR (BrasilAPI)."""

    id = "opencorporates"
    funcao = "ownership"

    def __init__(self):
        self._rl = RateLimiter(2)

    def disponivel(self) -> bool:
        return bool(os.getenv("OPENCORPORATES_API_TOKEN", "").strip())

    def consultar(self, *, nome: str | None = None, lei: str | None = None, **_) -> Resultado:
        if not nome:
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", "sem 'nome'")
        token = os.getenv("OPENCORPORATES_API_TOKEN", "").strip()
        self._rl.aguardar()
        try:
            r = httpx.get("https://api.opencorporates.com/v0.4/companies/search",
                          params={"q": nome, "api_token": token, "per_page": 5}, timeout=20)
            if r.status_code == 200:
                comps = (((r.json() or {}).get("results") or {}).get("companies")) or []
                hits = [{"nome": (c.get("company") or {}).get("name"),
                         "jurisdicao": (c.get("company") or {}).get("jurisdiction_code"),
                         "numero": (c.get("company") or {}).get("company_number"),
                         "url": (c.get("company") or {}).get("opencorporates_url")}
                        for c in comps]
                return Resultado(True, {"n": len(hits), "hits": hits}, self.id, agora_iso())
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", f"HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", str(e)[:80])
