# -*- coding: utf-8 -*-
"""Coletor Querido Diário — trava a regressão que o matou em silêncio.

O host `queridodiario.ok.org.br/api/*` é a SPA do site: devolve HTTP 200 com HTML. O código
antigo apontava para lá, chamava `.json()`, o `except` engolia a exceção e o coletor retornava
[] para sempre — sem log, sem erro. Estes testes prendem o host e os nomes de parâmetro reais.
"""
import asyncio

import httpx
import pytest

from compliance_agent.collectors import querido_diario as qd


def _rodar(coro):
    return asyncio.run(coro)


def test_aponta_para_o_backend_e_nao_para_a_spa():
    assert qd.QD_API.startswith("https://api.queridodiario.ok.org.br")
    assert "/api/" not in qd.QD_API


def test_usa_os_nomes_de_parametro_que_a_api_respeita(monkeypatch):
    """`territory_id`/`since`/`until` são IGNORADOS pela API (sem erro) — a busca vinha do
    Brasil inteiro em vez do RJ. Os nomes válidos são `territory_ids`/`published_*`."""
    capturado = {}

    async def falso_get(self, url, params=None, headers=None):
        capturado.update(params)
        return httpx.Response(200, json={"gazettes": []},
                              headers={"content-type": "application/json"})

    monkeypatch.setattr(httpx.AsyncClient, "get", falso_get)
    from datetime import date
    _rodar(qd.buscar_historico("teste", desde=date(2025, 1, 1), ate=date(2025, 12, 31)))

    assert capturado["territory_ids"] == qd.RJ_TERRITORY
    assert capturado["published_since"] == "2025-01-01"
    assert capturado["published_until"] == "2025-12-31"
    assert "territory_id" not in capturado and "since" not in capturado


def test_html_com_200_nao_passa_por_sucesso(monkeypatch, caplog):
    async def falso_get(self, url, params=None, headers=None):
        return httpx.Response(200, text="<!DOCTYPE html><html>SPA</html>",
                              headers={"content-type": "text/html"})

    monkeypatch.setattr(httpx.AsyncClient, "get", falso_get)
    with caplog.at_level("WARNING"):
        assert _rodar(qd.buscar_historico("teste")) == []
    assert any("inesperada" in r.message for r in caplog.records), "falha tem de deixar rastro"


def test_resposta_valida_e_devolvida(monkeypatch):
    async def falso_get(self, url, params=None, headers=None):
        return httpx.Response(200, json={"gazettes": [{"date": "2026-01-02", "excerpts": []}]},
                              headers={"content-type": "application/json"})

    monkeypatch.setattr(httpx.AsyncClient, "get", falso_get)
    assert _rodar(qd.buscar_historico("teste"))[0]["date"] == "2026-01-02"


def test_classificacao_de_trecho_marca_sancao(monkeypatch):
    async def falso_get(self, url, params=None, headers=None):
        return httpx.Response(200, headers={"content-type": "application/json"}, json={
            "gazettes": [{"date": "2026-01-02", "url": "u",
                          "excerpts": [{"text": "aplicada MULTA à empresa"}]}]})

    monkeypatch.setattr(httpx.AsyncClient, "get", falso_get)
    h = _rodar(qd.historico_empresa("ACME LTDA"))
    assert h["tem_sancao_historica"] is True and h["tipos"]["sancao"] == 1


def test_erro_de_rede_nao_estoura_e_deixa_log(monkeypatch, caplog):
    async def falso_get(self, url, params=None, headers=None):
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(httpx.AsyncClient, "get", falso_get)
    with caplog.at_level("WARNING"):
        assert _rodar(qd.buscar_historico("teste")) == []
    assert any("indisponível" in r.message for r in caplog.records)
