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


def test_midia_adversa_classifica_por_termo_de_risco(monkeypatch):
    from compliance_agent.enrich import midia_adversa

    class _R:
        status_code = 200
        def json(self):
            return {"articles": [
                {"title": "Empresa X é alvo de operação por fraude em licitação", "domain": "g1.globo.com",
                 "url": "http://g1/1", "seendate": "20260101T000000Z"},
                {"title": "Empresa X inaugura nova fábrica", "domain": "valor.com", "url": "http://v/2",
                 "seendate": "20260102T000000Z"},
            ]}

    monkeypatch.setattr("compliance_agent.enrich.midia_adversa.httpx.get", lambda *a, **k: _R())
    r = midia_adversa.varrer("Empresa X")
    assert r["ok"] is True and r["n_total"] == 2 and r["n_adversos"] == 1
    adv = r["adversos"][0]
    assert "operação" in adv["termos"] or "fraude" in adv["termos"]
    assert adv["fonte"] == "g1.globo.com"


def test_midia_adversa_erro_reporta_indisponivel(monkeypatch):
    from compliance_agent.enrich import midia_adversa

    def _boom(*a, **k):
        raise RuntimeError("rate limit")

    monkeypatch.setattr("compliance_agent.enrich.midia_adversa.httpx.get", _boom)
    r = midia_adversa.varrer("Empresa Y")
    assert r["ok"] is True and r["adversos"] == [] and "INDISPONÍVEL" in r["_nota"]


def test_capability_grafo_ftm_pronto():
    from compliance_agent.skilltree import SkillTree
    st = SkillTree()
    st.reload()
    cap = st.capacidades.get("grafo_ftm")
    assert cap is not None and cap["status"] == "PRONTO" and cap["rota"] == "/api/grafo/ftm"
    assert st.validate() == []


def test_exif_arquivo_inexistente():
    from compliance_agent.enrich import exif
    r = exif.metadados("/tmp/nao_existe_jfn_xyz.pdf")
    # com ExifTool instalado → erro de arquivo; sem ExifTool → INDISPONÍVEL (ambos honestos, nunca fabrica)
    assert (r.get("ok") is False and "não encontrado" in r.get("erro", "")) or "INDISPONÍVEL" in r.get("_nota", "")


def test_exif_le_pdf_real():
    """Lê metadados de um PDF real (um relatório já gerado), se houver ExifTool + arquivo."""
    import glob
    from compliance_agent.enrich import exif
    if not exif._disponivel():
        import pytest
        pytest.skip("ExifTool não instalado")
    pdfs = glob.glob("reports/*.pdf")
    if not pdfs:
        import pytest
        pytest.skip("sem PDF de amostra em reports/")
    r = exif.metadados(pdfs[0])
    assert r["ok"] is True and "meta" in r and "sinais" in r
    assert r["meta"].get("tipo") in ("PDF", None)  # ExifTool reporta FileType=PDF
