# -*- coding: utf-8 -*-
"""Testes da Onda 12 (OSINT/DD enrichment): export FollowTheMoney + OpenSanctions (key-gated)."""
from __future__ import annotations


def test_grafo_ftm_export_mapeia_schemas(monkeypatch):
    """Vizinhança → entidades FtM válidas (Company/Person/PublicBody + relações)."""
    from compliance_agent import grafo_ftm

    fake_g = {
        "ok": True, "raiz": "cnpj:11111111000111",
        "nos": [
            {"id": "cnpj:11111111000111", "tipo": "cnpj", "label": "EMPRESA A"},
            {"id": "socio:FULANO", "tipo": "socio", "label": "FULANO"},
            {"id": "ug:270042", "tipo": "ug", "label": "ITERJ"},
        ],
        "arestas": [
            {"de": "cnpj:11111111000111", "para": "socio:FULANO", "rel": "socio"},
            {"de": "cnpj:11111111000111", "para": "ug:270042", "rel": "pago_por", "total_ob": 5000.0},
        ],
    }
    monkeypatch.setattr("compliance_agent.grafo_poder.vizinhanca", lambda *a, **k: fake_g)
    r = grafo_ftm.export("11111111000111")
    assert r["ok"] is True
    schemas = {e["schema"] for e in r["entidades"]}
    assert {"Company", "Person", "PublicBody", "Ownership", "Payment"} <= schemas
    comp = next(e for e in r["entidades"] if e["schema"] == "Company")
    assert comp["properties"]["registrationNumber"] == ["11111111000111"]


def test_grafo_ftm_alvo_inexistente(monkeypatch):
    from compliance_agent import grafo_ftm
    monkeypatch.setattr("compliance_agent.grafo_poder.vizinhanca",
                        lambda *a, **k: {"ok": True, "nos": [], "_nota": "INDISPONÍVEL"})
    r = grafo_ftm.export("99999999999999")
    assert r["ok"] is True and r["entidades"] == []


def test_opensanctions_sem_chave_indisponivel(monkeypatch):
    from compliance_agent.enrich import opensanctions
    monkeypatch.delenv("OPENSANCTIONS_API_KEY", raising=False)
    r = opensanctions.checar("Petrobras")
    assert r["ok"] is True and r["sancionado"] is None and "INDISPONÍVEL" in r["_nota"]


def test_opensanctions_parseia_match(monkeypatch):
    from compliance_agent.enrich import opensanctions

    class _R:
        status_code = 200
        def json(self):
            return {"results": [{"caption": "Fulano PEP", "schema": "Person",
                                 "properties": {"topics": ["role.pep"]}, "score": 0.9}]}

    monkeypatch.setenv("OPENSANCTIONS_API_KEY", "x")
    monkeypatch.setattr("compliance_agent.enrich.opensanctions.httpx.get", lambda *a, **k: _R())
    r = opensanctions.checar("Fulano")
    assert r["ok"] is True and r["pep"] is True and r["matches"][0]["nome"] == "Fulano PEP"


def test_aleph_sem_chave_indisponivel(monkeypatch):
    from compliance_agent.enrich import aleph
    monkeypatch.delenv("ALEPH_API_KEY", raising=False)
    r = aleph.buscar("Construtora X")
    assert r["ok"] is True and r["matches"] == [] and "INDISPONÍVEL" in r["_nota"]


def test_aleph_parseia_match(monkeypatch):
    from compliance_agent.enrich import aleph

    class _R:
        status_code = 200
        def json(self):
            return {"total": {"value": 1},
                    "results": [{"id": "ent.123", "caption": "ACME LTDA", "schema": "Company",
                                 "properties": {"name": ["ACME LTDA"], "country": ["br"]},
                                 "collection": {"label": "Brasil Empresas"}}]}

    monkeypatch.setenv("ALEPH_API_KEY", "x")
    monkeypatch.setattr("compliance_agent.enrich.aleph.httpx.get", lambda *a, **k: _R())
    r = aleph.buscar("ACME")
    assert r["ok"] is True and r["total"] == 1
    assert r["matches"][0]["nome"] == "ACME LTDA"
    assert r["matches"][0]["link"].endswith("ent.123")


def test_capability_grafo_ftm_pronto():
    from compliance_agent.skilltree import SkillTree
    st = SkillTree()
    st.reload()
    cap = st.capacidades.get("grafo_ftm")
    assert cap is not None and cap["status"] == "PRONTO" and cap["rota"] == "/api/grafo/ftm"
    assert st.validate() == []
