# -*- coding: utf-8 -*-
"""Servidor que responde "não" em 0,2 s não merece 60 s de espera.

Medido em 31/07/2026, varrendo as 120 rotas GET da API: `/api/pncp` e
`/api/sei/direcionamento` deram **timeout aos 60 s**. O PNCP estava fora e respondia
HTTP 503 `text/html` em **0,2 s** — a fonte não estava lenta, estava recusando.

Os 60 s eram nossos: `_consulta_retry` faz 3 tentativas com `sleep(20*(i+1))` = 20 s + 40 s de sono
puro, porque `_get_consulta` engolia o status e devolvia `None` igual para timeout e para 5xx. Com
`modalidade=0` a rota varre 4 modalidades — ~240 s de página travada para o auditor.

A correção NÃO é encurtar a paciência: o backoff longo foi escrito de propósito para o caso
documentado no código (*"o PNCP devolve timeout transitório sob volume"*), e os coletores em lote
dependem dele. O que faltava era **distinguir os dois casos**:

  • falha de REDE (timeout, conexão recusada) → congestionamento nosso/da rota: espera longa;
  • resposta HTTP de erro (5xx/4xx) → o servidor respondeu, e respondeu "não": espera curta.

Insistir 60 s contra um 503 instantâneo não ajuda ninguém — se a fonte caiu, ela caiu, e o sweep
volta na próxima janela.
"""
from __future__ import annotations

import asyncio

import pytest

import compliance_agent.collectors.pncp as P


class _Resp:
    def __init__(self, status):
        self.status_code = status

    def json(self):
        return {"data": []}


def _cliente(efeito):
    """`httpx.AsyncClient` falso: `efeito` decide o que cada GET faz."""
    class _C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, *_a, **_kw):
            return efeito()
    return lambda *a, **k: _C()


@pytest.fixture()
def sem_sono(monkeypatch):
    """Não dorme de verdade — registra QUANTO teria dormido."""
    dormidas: list[float] = []

    async def _falso(s):
        dormidas.append(s)

    monkeypatch.setattr(P.asyncio, "sleep", _falso)
    return dormidas


def test_erro_http_instantaneo_tem_espera_curta(monkeypatch, sem_sono):
    """O caso medido: 503 em 0,2 s não pode custar 60 s de sono."""
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _cliente(lambda: _Resp(503)))

    asyncio.run(P._consulta_retry("/contratacoes/publicacao", {}))

    assert sum(sem_sono) <= 10, (
        f"esperou {sum(sem_sono)}s contra um servidor que respondeu na hora: {sem_sono}")


def test_falha_de_rede_mantem_a_espera_longa(monkeypatch, sem_sono):
    """Congestionamento é o caso para o qual o backoff longo foi escrito — segue igual."""
    import httpx

    def _estoura():
        raise httpx.ReadTimeout("demorou")

    monkeypatch.setattr(httpx, "AsyncClient", _cliente(_estoura))

    asyncio.run(P._consulta_retry("/contratacoes/publicacao", {}))

    assert sum(sem_sono) >= 40, (
        f"a paciencia do coletor em lote foi encurtada por engano: {sem_sono}")


def test_resposta_boa_nao_dorme_nem_retenta(monkeypatch, sem_sono):
    """Guarda-costas do caminho feliz."""
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _cliente(lambda: _Resp(200)))

    assert asyncio.run(P._consulta_retry("/contratacoes/publicacao", {})) == {"data": []}
    assert sem_sono == []


def test_get_consulta_ainda_devolve_dict_para_quem_so_quer_o_json(monkeypatch):
    """`buscar_contratacoes` (o outro chamador) não pode receber tupla onde espera dict."""
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _cliente(lambda: _Resp(200)))

    j, motivo = asyncio.run(P._get_consulta("/x", {}))
    assert j == {"data": []} and motivo == "ok"


def test_motivo_separa_rede_de_http(monkeypatch):
    """O motivo é o que permite ao retry escolher a espera — sem ele o defeito volta."""
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _cliente(lambda: _Resp(503)))
    assert asyncio.run(P._get_consulta("/x", {}))[1] == "http"

    def _estoura():
        raise httpx.ConnectError("recusou")

    monkeypatch.setattr(httpx, "AsyncClient", _cliente(_estoura))
    assert asyncio.run(P._get_consulta("/x", {}))[1] == "rede"
