# -*- coding: utf-8 -*-
"""Sanções/idoneidade — Brasil (CEIS/CNEP via Portal da Transparência) + intl/PEP (OpenSanctions).

OpenSanctions reusa o módulo enrich/opensanctions (mesma chave OPENSANCTIONS_API_KEY) — agrega, não duplica.
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


class OpenSanctionsSearch:
    id = "opensanctions"
    funcao = "sanctions"

    def __init__(self):
        self._rl = RateLimiter(2)

    def disponivel(self) -> bool:
        return True  # busca pública; chave amplia o limite

    def consultar(self, *, cnpj: str | None = None, nome: str | None = None, **_) -> Resultado:
        alvo = (nome or cnpj or "").strip()
        if not alvo:
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", "sem 'nome'/'cnpj'")
        self._rl.aguardar()
        try:
            # reusa o enricher honesto já existente (key-gated, nunca fabrica)
            from compliance_agent.enrich.opensanctions import checar
            r = checar(alvo)
            if r.get("matches") is not None and (r.get("sancionado") is not None or r.get("matches")):
                return Resultado(True, {"sancionado": r.get("sancionado"), "pep": r.get("pep"),
                                        "n": len(r.get("matches") or []), "matches": r.get("matches")},
                                 self.id, agora_iso())
            # sem chave → enricher devolve INDISPONÍVEL honesto
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL",
                             r.get("_nota", "sem resultado"))
        except Exception as e:  # noqa: BLE001
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", str(e)[:80])
