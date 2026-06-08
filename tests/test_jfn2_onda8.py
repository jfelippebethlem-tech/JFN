# -*- coding: utf-8 -*-
"""Testes da Onda 8 (Massare notícia/macro/fundamento) — determinísticos, httpx mockado."""
from __future__ import annotations


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


def test_news_coletar_parseia(monkeypatch):
    from massare import news

    def fake_get(url, **k):
        return _FakeResp(200, {"articles": [
            {"title": "Petrobras sobe", "domain": "g1.com", "seendate": "20260608T00", "url": "u", "language": "Portuguese"}]})

    monkeypatch.setattr("massare.news.httpx.get", fake_get)
    r = news.coletar("Petrobras", "2d")
    assert r["ok"] is True and r["n"] == 1
    assert r["artigos"][0]["fonte"] == "g1.com" and r["artigos"][0]["titulo"] == "Petrobras sobe"


def test_news_429_honesto(monkeypatch):
    from massare import news

    monkeypatch.setattr("massare.news.httpx.get", lambda url, **k: _FakeResp(429, {}))
    r = news.coletar("x")
    assert r["ok"] is False and "429" in r["erro"]  # honesto, não fabrica


def test_calendar_sem_chave_indisponivel(monkeypatch):
    from massare import calendar as cal

    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    r = cal.agenda()
    assert r["ok"] is True and r["eventos"] == [] and "INDISPONÍVEL" in r["_nota"]  # não fabrica agenda


def test_fundamentos_parseia(monkeypatch):
    from massare import fundamentos as F

    def fake_get(url, **k):
        return _FakeResp(200, {"results": [{"regularMarketPrice": 40.89, "priceEarnings": 8.1,
                                            "dividendYield": 0.12, "longName": "PETROBRAS PN",
                                            "financialData": {"returnOnEquity": 0.25}}]})

    monkeypatch.setattr("massare.fundamentos.httpx.get", fake_get)
    r = F.fundamentos("petr4")
    assert r["ok"] is True and r["ticker"] == "PETR4"
    assert r["preco"] == 40.89 and r["pl"] == 8.1 and r["roe"] == 0.25


def test_fundamentos_sem_ticker():
    from massare.fundamentos import fundamentos
    assert fundamentos("")["ok"] is False


def test_capabilities_massare_onda8_pronto():
    from compliance_agent.skilltree import SkillTree

    st = SkillTree()
    st.reload()
    for cid in ("massare_focus", "massare_calendario", "massare_fundamentos"):
        cap = st.capacidades.get(cid)
        assert cap is not None and cap["status"] == "PRONTO", cid
    assert st.validate() == []
