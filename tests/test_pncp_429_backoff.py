# -*- coding: utf-8 -*-
"""HTTP 429 é o PNCP pedindo para esperar — não é erro comum de 2 s.

Medido no run de 09/11/2026 do `jfn-fisc-refresh`: **751 respostas 429** (e 46 503). O
`_get_consulta` devolvia `"http"` para o 429, o retry dormia 2/4 s e desistia na 3ª — semestre
com buraco, gravado como se a fonte tivesse respondido. Agora: motivo próprio (`"limite"`),
backoff exponencial que respeita o `Retry-After` (com teto) e um limite de tentativas.
"""
from __future__ import annotations

import asyncio

import pytest

import compliance_agent.collectors.pncp as P


class _Resp:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        return {"data": [1]}


def _cliente(efeitos):
    it = iter(efeitos)

    class _C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, *_a, **_kw):
            return next(it)
    return lambda *a, **k: _C()


@pytest.fixture()
def sem_sono(monkeypatch):
    dormidas: list[float] = []

    async def _falso(s):
        dormidas.append(s)

    monkeypatch.setattr(P.asyncio, "sleep", _falso)
    return dormidas


def test_429_tem_motivo_proprio(monkeypatch):
    monkeypatch.setattr(P.httpx, "AsyncClient", _cliente([_Resp(429)]))
    assert asyncio.run(P._get_consulta("/x", {}))[1] == "limite"


def test_429_respeita_retry_after_e_depois_entrega(monkeypatch, sem_sono):
    monkeypatch.setattr(P.httpx, "AsyncClient", _cliente(
        [_Resp(429, {"Retry-After": "17"}), _Resp(429, {"Retry-After": "17"}), _Resp(200)]))
    assert asyncio.run(P._consulta_retry("/contratos", {})) == {"data": [1]}
    assert sem_sono[0] >= 17 and sem_sono[1] >= 17


def test_429_sem_retry_after_cresce_exponencial(monkeypatch, sem_sono):
    monkeypatch.setattr(P.httpx, "AsyncClient", _cliente([_Resp(429)] * 10))
    assert asyncio.run(P._consulta_retry("/contratos", {})) is None
    assert len(sem_sono) == P._TENTATIVAS_429 - 1, "limite de tentativas"
    assert all(b > a for a, b in zip(sem_sono, sem_sono[1:])), sem_sono


def test_retry_after_absurdo_tem_teto(monkeypatch, sem_sono):
    monkeypatch.setattr(P.httpx, "AsyncClient", _cliente(
        [_Resp(429, {"Retry-After": "86400"}), _Resp(200)]))
    asyncio.run(P._consulta_retry("/contratos", {}))
    assert sem_sono == [P._TETO_ESPERA_429]
