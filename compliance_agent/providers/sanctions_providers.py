# -*- coding: utf-8 -*-
"""Sanções/idoneidade — Brasil (CEIS/CNEP via Portal da Transparência).

OpenSanctions removido 2026-07-18 (decisão do dono): exigia chave grátis nunca provida e só gerava
INDISPONÍVEL nas perícias. Idoneidade doméstica (CEIS/CNEP/CEPIM) é a fonte da casa.
"""
from __future__ import annotations

import os

import httpx

from .base import RateLimiter, Resultado, agora_iso


class PortalTransparenciaCEIS:
    id = "transparencia_ceis"
    funcao = "sanctions"

    def __init__(self):
        self._rl = RateLimiter(5)

    def disponivel(self) -> bool:
        return bool(os.getenv("PORTAL_TRANSPARENCIA_KEY", "").strip())

    def consultar(self, *, cnpj: str | None = None, nome: str | None = None, **_) -> Resultado:
        self._rl.aguardar()
        key = os.getenv("PORTAL_TRANSPARENCIA_KEY", "").strip()
        try:
            params = {"pagina": 1}
            if cnpj:
                params["codigoSancionado"] = cnpj
            r = httpx.get("https://api.portaldatransparencia.gov.br/api-de-dados/ceis",
                          params=params, headers={"chave-api-dados": key}, timeout=20)
            if r.status_code == 200:
                lst = r.json()
                return Resultado(True, {"fonte_lista": "CEIS/CNEP", "n": len(lst), "sancoes": lst},
                                 self.id, agora_iso())
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", f"HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", str(e)[:80])
