# -*- coding: utf-8 -*-
"""Singleton + facade da camada providers. Ordem de registro = prioridade (base ungated primeiro).

Adicionar um backend novo (ex.: OpenCorporates quando a chave sair) = 1 classe + 1 linha aqui,
sem tocar nas rotas."""
from __future__ import annotations

from .base import CacheSQLite, Providers, Resultado
from .gazettes_providers import QueridoDiario
from .leaks_providers import OffshoreLeaksLink
from .links_providers import InvestigacaoHospedada
from .ownership_providers import GLEIF, OpenCorporates
from .registry_providers import BrasilAPICNPJ, CNPJpw, CNPJws, OpenCNPJ
from .sanctions_providers import OpenSanctionsSearch, PortalTransparenciaCEIS

_PROV: Providers | None = None


def get_providers() -> Providers:
    global _PROV
    if _PROV is None:
        p = Providers(CacheSQLite())
        # registry (Onda 12): cadeia BrasilAPI→OpenCNPJ→CNPJ.ws (todas ungated; OpenCNPJ/CNPJ.ws
        # confirmados ao vivo). CNPJpw (api.cnpj.pw) como último fallback. BrasilAPI tem rate-limit
        # agressivo (429) — por isso a cadeia importa.
        for b in (BrasilAPICNPJ(), OpenCNPJ(), CNPJws(), CNPJpw()):  # registry (fallback em ordem)
            p.registrar(b)
        for b in (PortalTransparenciaCEIS(), OpenSanctionsSearch()):  # sanctions (lookup_all)
            p.registrar(b)
        for b in (GLEIF(), OpenCorporates()):  # ownership (GLEIF sem chave; OpenCorporates key-gated)
            p.registrar(b)
        p.registrar(OffshoreLeaksLink())  # leaks
        p.registrar(InvestigacaoHospedada())  # links (agregadores hospedados)
        p.registrar(QueridoDiario())  # gazettes (diários municipais — Querido Diário)
        _PROV = p
    return _PROV


def lookup(funcao: str, **q) -> Resultado:
    return get_providers().lookup(funcao, **q)


def lookup_all(funcao: str, **q) -> list[Resultado]:
    return get_providers().lookup_all(funcao, **q)
