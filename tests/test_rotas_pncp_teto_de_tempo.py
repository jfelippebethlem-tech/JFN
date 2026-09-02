# -*- coding: utf-8 -*-
"""Rota que depende de fonte externa nunca pode pendurar o painel.

Health-check de 2026-08-02 nas 137 rotas GET: duas devolveram `000` (conexão pendurada, sem
resposta em 25 s) — `/api/pncp` e `/api/sei/direcionamento`. Ambas aguardam o PNCP ao vivo sem
teto de tempo e, ao contrário das vizinhas pesadas do mesmo arquivo, sem cache. Para o usuário
do painel isso é a aba morrer: nem dado, nem erro, nem "indisponível".

Regra: teto de tempo + resposta honesta. INDISPONÍVEL ≠ 0 e ≠ silêncio.
"""
from __future__ import annotations

import asyncio
import warnings

warnings.filterwarnings("ignore")


def _client():
    from fastapi.testclient import TestClient

    import server

    return TestClient(server.app)


async def _nunca_responde(*a, **k):
    await asyncio.sleep(600)


def test_pncp_devolve_indisponivel_em_vez_de_pendurar(monkeypatch):
    from compliance_agent.collectors import pncp
    from rotas import investigacao

    monkeypatch.setattr(pncp, "buscar_contratacoes", _nunca_responde)
    monkeypatch.setattr(investigacao, "_TETO_FONTE_VIVA", 1.0)
    r = _client().get("/api/pncp?dias=1")
    assert r.status_code == 200
    j = r.json()
    assert j.get("indisponivel") is True, "a rota tem de admitir a indisponibilidade"
    assert j.get("n") in (0, None)
    assert "_nota" in j and "não respondeu" in j["_nota"].lower()


def test_sei_direcionamento_devolve_indisponivel_em_vez_de_pendurar(monkeypatch):
    from compliance_agent import sei_direcionamento
    from rotas import investigacao

    monkeypatch.setattr(sei_direcionamento, "varrer_direcionamento", _nunca_responde)
    monkeypatch.setattr(investigacao, "_TETO_FONTE_VIVA", 1.0)
    r = _client().get("/api/sei/direcionamento?max_itens=1")
    assert r.status_code == 200
    j = r.json()
    assert j.get("indisponivel") is True
    assert "não respondeu" in j.get("_nota", "").lower()


def test_indisponivel_nao_e_cacheado_como_resposta_boa(monkeypatch):
    """Cachear o timeout congelaria a aba vazia por 1 h — pior que o bug original."""
    from compliance_agent.collectors import pncp
    from rotas import investigacao

    monkeypatch.setattr(pncp, "buscar_contratacoes", _nunca_responde)
    monkeypatch.setattr(investigacao, "_TETO_FONTE_VIVA", 1.0)
    c = _client()
    c.get("/api/pncp?dias=3&uf=SP")

    chamadas = {"n": 0}

    async def responde(*a, **k):
        chamadas["n"] += 1
        return [{"orgao": "X", "orgao_cnpj": "1", "unidade": "U", "municipio": "Rio"}]

    monkeypatch.setattr(pncp, "buscar_contratacoes", responde)
    j = c.get("/api/pncp?dias=3&uf=SP").json()
    assert chamadas["n"] == 1, "o timeout ficou cacheado e a fonte nunca mais foi consultada"
    assert j["n"] == 1 and not j.get("indisponivel")
