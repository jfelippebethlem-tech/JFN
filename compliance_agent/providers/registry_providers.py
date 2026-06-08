# -*- coding: utf-8 -*-
"""Registry — empresa + sócios (Brasil), base ungated hospedada. BrasilAPI → cnpj.pw (fallback)."""
from __future__ import annotations

import re

import httpx

from .base import RateLimiter, Resultado, agora_iso


def _digitos(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


class BrasilAPICNPJ:
    id = "brasilapi"
    funcao = "registry"

    def __init__(self):
        self._rl = RateLimiter(3)

    def disponivel(self) -> bool:
        return True

    def consultar(self, *, cnpj: str, **_) -> Resultado:
        self._rl.aguardar()
        c = _digitos(cnpj)
        try:
            r = httpx.get(f"https://brasilapi.com.br/api/cnpj/v1/{c}", timeout=15)
            if r.status_code == 200:
                d = r.json()
                return Resultado(True, {
                    "cnpj": d.get("cnpj"),
                    "razao_social": d.get("razao_social"),
                    "situacao": d.get("descricao_situacao_cadastral"),
                    "abertura": d.get("data_inicio_atividade"),
                    "cnae": d.get("cnae_fiscal_descricao"),
                    "municipio": d.get("municipio"),
                    "uf": d.get("uf"),
                    "socios": [
                        {"nome": s.get("nome_socio"), "doc": s.get("cnpj_cpf_do_socio"),
                         "qualificacao": s.get("qualificacao_socio")}
                        for s in (d.get("qsa") or [])
                    ],
                }, self.id, agora_iso())
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", f"HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", str(e)[:80])


class CNPJpw:
    id = "cnpjpw"
    funcao = "registry"

    def __init__(self):
        self._rl = RateLimiter(8)  # host limita ~10/s

    def disponivel(self) -> bool:
        return True

    def consultar(self, *, cnpj: str, **_) -> Resultado:
        self._rl.aguardar()
        c = _digitos(cnpj)
        try:
            r = httpx.get(f"https://api.cnpj.pw/cnpj/{c}", timeout=15,
                          headers={"User-Agent": "JFN/2.0"})
            if r.status_code == 200:
                return Resultado(True, r.json(), self.id, agora_iso())
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", f"HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", str(e)[:80])
