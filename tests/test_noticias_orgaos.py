# -*- coding: utf-8 -*-
"""Imprensa por órgão (Google News RSS): classificação por termo de risco e dedupe por url (12/09/2026)."""
from __future__ import annotations

from tools import noticias_orgaos as N


def test_coletar_classifica_e_materializar_deduplica(tmp_path, monkeypatch):
    fake = [{"title": "Fundação Saúde é alvo de operação por fraude em contratos", "url": "http://x/1", "seendate": "Thu, 26 Feb 2026 10:00:00 GMT", "domain": "g1"},
            {"title": "Fundação Saúde inaugura UPA", "url": "http://x/2", "seendate": "Fri, 27 Feb 2026 10:00:00 GMT", "domain": "odia"}]
    monkeypatch.setattr("compliance_agent.enrich.midia_adversa._gnews", lambda q, max_r=30: (fake, ""))
    itens = N.coletar([('"Fundação Saúde"', "FSERJ")], pausa=0)
    assert [i["adversa"] for i in itens] == [1, 0] and itens[0]["termos"] == "fraude,operação" and itens[0]["data"].startswith("2026-02-26")
    monkeypatch.setattr(N, "DB", tmp_path / "c.db")
    r1 = N.materializar(itens); r2 = N.materializar(itens)
    assert r1["novas"] == 2 and r2["novas"] == 0 and r2["total"] == 2 and r2["adversas"] == 1


def test_nome_do_orgao_nao_e_termo_de_risco(monkeypatch):
    fake = [{"title": "TCE-RJ aprova contas do governo", "url": "http://x/3", "seendate": "Thu, 26 Feb 2026 10:00:00 GMT", "domain": "g1"},
            {"title": "TCE-RJ aponta fraude em contrato da Fundação", "url": "http://x/4", "seendate": "Thu, 26 Feb 2026 10:00:00 GMT", "domain": "g1"}]
    monkeypatch.setattr("compliance_agent.enrich.midia_adversa._gnews", lambda q, max_r=30: (fake, ""))
    itens = N.coletar([('"TCE-RJ"', "TCE-RJ")], pausa=0)
    assert [i["adversa"] for i in itens] == [0, 1] and itens[1]["termos"] == "fraude"
