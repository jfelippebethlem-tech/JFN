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


class OpenCNPJ:
    """api.opencnpj.org — base ungated da Receita (CNAE + QSA). Confirmado ao vivo 2026-06-08."""
    id = "opencnpj"
    funcao = "registry"

    def __init__(self):
        self._rl = RateLimiter(3)

    def disponivel(self) -> bool:
        return True

    def consultar(self, *, cnpj: str, **_) -> Resultado:
        self._rl.aguardar()
        c = _digitos(cnpj)
        try:
            r = httpx.get(f"https://api.opencnpj.org/{c}", timeout=15,
                          headers={"User-Agent": "JFN/2.0"})
            if r.status_code == 200:
                d = r.json()
                return Resultado(True, {
                    "cnpj": d.get("cnpj"),
                    "razao_social": d.get("razao_social"),
                    "situacao": d.get("situacao_cadastral"),
                    "abertura": d.get("data_inicio_atividade"),
                    "cnae": d.get("cnae_principal"),
                    "municipio": d.get("municipio"),
                    "uf": d.get("uf"),
                    "socios": [
                        {"nome": s.get("nome_socio"), "doc": s.get("cnpj_cpf_socio"),
                         "qualificacao": s.get("qualificacao_socio")}
                        for s in (d.get("QSA") or [])
                    ],
                }, self.id, agora_iso())
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", f"HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", str(e)[:80])


class CNPJws:
    """publica.cnpj.ws — base ungated (~3 req/min). CNAE com descrição + QSA. Confirmado ao vivo 2026-06-08."""
    id = "cnpjws"
    funcao = "registry"

    def __init__(self):
        self._rl = RateLimiter(0.4)  # público ~3/min — folga p/ não tomar 429

    def disponivel(self) -> bool:
        return True

    def consultar(self, *, cnpj: str, **_) -> Resultado:
        self._rl.aguardar()
        c = _digitos(cnpj)
        try:
            r = httpx.get(f"https://publica.cnpj.ws/cnpj/{c}", timeout=15,
                          headers={"User-Agent": "JFN/2.0"})
            if r.status_code == 200:
                d = r.json()
                est = d.get("estabelecimento") or {}
                ap = est.get("atividade_principal") or {}
                estado = est.get("estado") or {}
                cidade = est.get("cidade") or {}
                return Resultado(True, {
                    "cnpj": est.get("cnpj"),
                    "razao_social": d.get("razao_social"),
                    "situacao": est.get("situacao_cadastral"),
                    "abertura": est.get("data_inicio_atividade"),
                    "cnae": ap.get("descricao") or ap.get("id"),
                    "municipio": cidade.get("nome"),
                    "uf": estado.get("sigla") or est.get("uf"),
                    "socios": [
                        {"nome": s.get("nome"), "doc": s.get("cpf_cnpj_socio"),
                         "qualificacao": s.get("tipo")}
                        for s in (d.get("socios") or [])
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
