# -*- coding: utf-8 -*-
"""Diários oficiais municipais (Querido Diário / Open Knowledge Brasil) — Onda 12.

API pública sem chave. Base confirmada ao vivo 2026-06-08: `https://api.queridodiario.ok.org.br`
(a base `queridodiario.ok.org.br/api` do spec está atrás de Cloudflare 403). Busca por palavra-chave
em diários, filtrando por município (IBGE `territory_ids`, ex.: Rio de Janeiro capital = 3304557).
On-demand + cache (não baixa base); proveniência REAL/CACHE como todo provider.
"""
from __future__ import annotations

import os

import httpx

from .base import RateLimiter, Resultado, agora_iso


class QueridoDiario:
    id = "querido_diario"
    funcao = "gazettes"

    def __init__(self):
        self._rl = RateLimiter(1)  # respeitar ~60/min
        self._base = os.environ.get("QUERIDODIARIO_BASE", "https://api.queridodiario.ok.org.br").rstrip("/")

    def disponivel(self) -> bool:
        return True

    def consultar(self, *, querystring: str, territory_ids: str = "", desde: str = "",
                  ate: str = "", size: int = 20, **_) -> Resultado:
        self._rl.aguardar()
        params: dict = {"querystring": querystring, "size": size}
        if territory_ids:
            params["territory_ids"] = territory_ids
        if desde:
            params["published_since"] = desde
        if ate:
            params["published_until"] = ate
        try:
            r = httpx.get(f"{self._base}/gazettes", params=params, timeout=25,
                          headers={"User-Agent": "JFN/2.0"})
            if r.status_code != 200:
                return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", f"HTTP {r.status_code}")
            j = r.json()
            itens = [
                {"municipio": g.get("territory_name"), "uf": g.get("state_code"),
                 "data": g.get("date"), "url": g.get("url") or g.get("txt_url"),
                 "trecho": g.get("excerpts"), "edicao_extra": g.get("is_extra_edition")}
                for g in (j.get("gazettes") or [])
            ]
            return Resultado(True, {"total": j.get("total_gazettes"), "itens": itens},
                             self.id, agora_iso())
        except Exception as e:  # noqa: BLE001
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", str(e)[:80])
