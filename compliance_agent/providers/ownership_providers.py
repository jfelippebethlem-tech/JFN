# -*- coding: utf-8 -*-
"""Ownership internacional / cross-jurisdição — GLEIF (LEI + relações de controle), sem chave.

Quando a chave do OpenCorporates sair, basta adicionar uma classe OpenCorporates(funcao='ownership')
e registrá-la no __init__ — sem tocar nas rotas (critério de aceite #7 do spec)."""
from __future__ import annotations

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
