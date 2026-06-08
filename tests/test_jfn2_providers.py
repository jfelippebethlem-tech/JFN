# -*- coding: utf-8 -*-
"""Onda 12 (reescrita) — camada providers/: fallback, cache TTL, proveniência, links hospedados."""
from __future__ import annotations

from compliance_agent.providers.base import CacheSQLite, Providers, Resultado, agora_iso


class _FakeOK:
    id = "ok"
    funcao = "registry"

    def disponivel(self):
        return True

    def consultar(self, **q):
        return Resultado(True, {"razao_social": "ACME", "socios": [{"nome": "F"}]}, self.id, agora_iso())


class _FakeFail:
    id = "fail"
    funcao = "registry"

    def disponivel(self):
        return True

    def consultar(self, **q):
        return Resultado(False, None, self.id, agora_iso(), "INDISPONIVEL", "HTTP 500")


def _prov(tmp_path, *backends):
    p = Providers(CacheSQLite(str(tmp_path / "c.db")))
    for b in backends:
        p.registrar(b)
    return p


def test_fallback_pula_backend_que_falha(tmp_path):
    p = _prov(tmp_path, _FakeFail(), _FakeOK())
    r = p.lookup("registry", cnpj="1")
    assert r.ok and r.fonte == "ok" and r.dados["razao_social"] == "ACME"


def test_cache_segunda_chamada_e_cache(tmp_path):
    p = _prov(tmp_path, _FakeOK())
    r1 = p.lookup("registry", cnpj="1")
    r2 = p.lookup("registry", cnpj="1")
    assert r1.estado == "REAL" and r2.estado == "CACHE" and r2.dados == r1.dados


def test_proveniencia_sempre_presente(tmp_path):
    p = _prov(tmp_path, _FakeFail())
    r = p.lookup("registry", cnpj="1")
    assert r.ok is False and r.estado == "INDISPONIVEL" and r.obtido_em and r.fonte


def test_registry_brasilapi_parseia(monkeypatch):
    from compliance_agent.providers import registry_providers as R

    class _Resp:
        status_code = 200
        def json(self):
            return {"cnpj": "1", "razao_social": "ACME LTDA", "descricao_situacao_cadastral": "ATIVA",
                    "qsa": [{"nome_socio": "FULANO", "cnpj_cpf_do_socio": "***1**", "qualificacao_socio": "Sócio"}]}

    monkeypatch.setattr(R.httpx, "get", lambda *a, **k: _Resp())
    r = R.BrasilAPICNPJ().consultar(cnpj="11.222.333/0001-44")
    assert r.ok and r.dados["razao_social"] == "ACME LTDA" and r.dados["socios"][0]["nome"] == "FULANO"


def test_links_hospedados_monta_deeplinks():
    from compliance_agent.providers.links_providers import InvestigacaoHospedada
    r = InvestigacaoHospedada().consultar(nome="MGS Clean", cnpj="19088605000104")
    fontes = {l["fonte"] for l in r.dados["links"]}
    assert "Max Intel" in fontes and "OSINT-Brazuca" in fontes and "RedeCNPJ" in fontes
    maxi = next(l for l in r.dados["links"] if l["fonte"] == "Max Intel")
    assert "MGS" in maxi["url"]


def test_leaks_offshore_link():
    from compliance_agent.providers.leaks_providers import OffshoreLeaksLink
    r = OffshoreLeaksLink().consultar(termo="ACME")
    assert r.ok and "offshoreleaks.icij.org" in r.dados["url"]


def test_singleton_registra_todas_as_funcoes():
    from compliance_agent.providers import get_providers
    p = get_providers()
    for funcao in ("registry", "sanctions", "ownership", "leaks", "links"):
        assert p.backends(funcao), f"sem backend para {funcao}"


def test_opencorporates_sem_token_indisponivel(monkeypatch):
    monkeypatch.delenv("OPENCORPORATES_API_TOKEN", raising=False)
    from compliance_agent.providers.ownership_providers import OpenCorporates
    oc = OpenCorporates()
    assert oc.disponivel() is False  # sem token → não entra no fallback (honesto)


def test_opencorporates_parseia_com_token(monkeypatch):
    monkeypatch.setenv("OPENCORPORATES_API_TOKEN", "x")
    from compliance_agent.providers import ownership_providers as O

    class _Resp:
        status_code = 200
        def json(self):
            return {"results": {"companies": [
                {"company": {"name": "ACME INC", "jurisdiction_code": "us_de",
                             "company_number": "123", "opencorporates_url": "http://oc/acme"}}]}}

    monkeypatch.setattr(O.httpx, "get", lambda *a, **k: _Resp())
    r = O.OpenCorporates().consultar(nome="ACME")
    assert r.ok and r.dados["hits"][0]["jurisdicao"] == "us_de"


def test_ownership_tem_gleif_e_opencorporates():
    from compliance_agent.providers import get_providers
    ids = {b.id for b in get_providers().backends("ownership")}
    assert {"gleif", "opencorporates"} <= ids
