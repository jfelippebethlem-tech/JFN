# -*- coding: utf-8 -*-
"""Testes do coletor de benefícios sociais (laranja) + PEP (relação política).

Sem rede: cobrem a HONESTIDADE (INDISPONÍVEL quando falta CPF/chave) e a normalização do PEP.
O caminho de rede real é exercido via monkeypatch do _get (não bate na API)."""
import asyncio

import pytest

from compliance_agent.collectors import beneficios_sociais as bs


def _run(coro):
    return asyncio.run(coro)


def test_beneficios_cpf_invalido_indisponivel(monkeypatch):
    monkeypatch.setenv("PORTAL_TRANSPARENCIA_KEY", "x")
    out = _run(bs.verificar_beneficios("123"))  # não tem 11 dígitos
    assert out["verificado"] is False and out["recebe_beneficio"] is None
    assert "mascarado" in out["motivo"] or "completo" in out["motivo"]


def test_beneficios_sem_chave_indisponivel(monkeypatch):
    monkeypatch.delenv("PORTAL_TRANSPARENCIA_KEY", raising=False)
    monkeypatch.delenv("TRANSPARENCIA_API_KEY", raising=False)
    bs._cache = None
    out = _run(bs.verificar_beneficios("11144477735"))
    assert out["verificado"] is False and "chave" in out["motivo"]


def test_beneficios_recebe(monkeypatch):
    monkeypatch.setenv("PORTAL_TRANSPARENCIA_KEY", "x")
    bs._cache = {}
    async def fake_get(client, endpoint, params, chave):
        return (True, [{"tipo": "x"}], "") if "peti" in endpoint else (True, [], "")
    monkeypatch.setattr(bs, "_get", fake_get)
    monkeypatch.setattr(bs, "_salva_cache", lambda: None)
    out = _run(bs.verificar_beneficios("11144477735"))
    assert out["verificado"] is True and out["recebe_beneficio"] is True
    assert any(b["tipo"] == "PETI" for b in out["beneficios"])


def test_beneficios_todos_falham_indisponivel(monkeypatch):
    monkeypatch.setenv("PORTAL_TRANSPARENCIA_KEY", "x")
    bs._cache = {}
    async def fake_get(client, endpoint, params, chave):
        return (False, [], "HTTP 500")
    monkeypatch.setattr(bs, "_get", fake_get)
    out = _run(bs.verificar_beneficios("11144477735"))
    assert out["verificado"] is False and out["recebe_beneficio"] is None


def test_bolsa_familia_envia_competencia_e_acha(monkeypatch):
    # BF exige anoMesReferencia (sem ela a API real dá HTTP 400). O coletor DEVE enviá-la → acha o benefício.
    monkeypatch.setenv("PORTAL_TRANSPARENCIA_KEY", "x")
    bs._cache = {}
    async def fake_get(client, endpoint, params, chave):
        if endpoint.startswith("bolsa-familia"):
            if "anoMesReferencia" not in params:
                return (False, [], "HTTP 400: Informe ano e mês de competência ou de referência.")
            return (True, [{"valor": 600}], "")  # competência presente → registro
        return (True, [], "")
    monkeypatch.setattr(bs, "_get", fake_get)
    monkeypatch.setattr(bs, "_salva_cache", lambda: None)
    out = _run(bs.verificar_beneficios("11144477735"))
    assert out["verificado"] is True and out["recebe_beneficio"] is True
    assert any(b["tipo"] == "Bolsa Família" for b in out["beneficios"])
    assert out["motivo"] == ""  # sem erro de competência → a competência foi enviada


def test_auxilio_emergencial_400_nao_beneficiario_nao_polui(monkeypatch):
    # 400 "CPF/NIS válido" do Aux. Emergencial p/ não-beneficiário = sem benefício, não INDISPONÍVEL nem erro.
    monkeypatch.setenv("PORTAL_TRANSPARENCIA_KEY", "x")
    bs._cache = {}
    async def fake_get(client, endpoint, params, chave):
        if endpoint.startswith("auxilio-emergencial"):
            return (False, [], "HTTP 400: Informe um CPF/NIS válido do Beneficiário ou Responsável Familiar")
        if endpoint.startswith("bolsa-familia"):
            return (True, [], "")  # competência respondeu vazio
        return (True, [], "")
    monkeypatch.setattr(bs, "_get", fake_get)
    monkeypatch.setattr(bs, "_salva_cache", lambda: None)
    out = _run(bs.verificar_beneficios("11144477735"))
    assert out["verificado"] is True and out["recebe_beneficio"] is False
    assert "Auxílio Emergencial" not in out["motivo"]  # 400 de não-beneficiário não vira erro


def test_ultimos_meses_ordem_e_virada_de_ano():
    meses = bs._ultimos_meses(3)
    assert len(meses) == 3 and all(len(m) == 6 for m in meses)
    assert meses[0] > meses[1] > meses[2]  # mais recente primeiro, sem mês 00


def test_pep_por_nome_curto_indisponivel(monkeypatch):
    monkeypatch.setenv("PORTAL_TRANSPARENCIA_KEY", "x")
    out = _run(bs.verificar_pep(nome="Zé"))
    assert out["verificado"] is False and out["eh_pep"] is None


def test_pep_por_nome_match(monkeypatch):
    monkeypatch.setenv("PORTAL_TRANSPARENCIA_KEY", "x")
    bs._cache = {}
    async def fake_get(client, endpoint, params, chave):
        assert endpoint == "peps" and params.get("nome")
        return (True, [{"nome": "FULANO DE TAL", "descricaoFuncao": "Deputado",
                        "nomeOrgao": "ALERJ", "dataInicioExercicio": "2023-01-01"}], "")
    monkeypatch.setattr(bs, "_get", fake_get)
    monkeypatch.setattr(bs, "_salva_cache", lambda: None)
    out = _run(bs.verificar_pep(nome="Fulano de Tal"))
    assert out["verificado"] is True and out["eh_pep"] is True
    assert out["peps"][0]["funcao"] == "Deputado"
    assert "homônimo" in out["motivo"]  # honestidade: match por nome é a confirmar


def test_pep_cpf_match_sem_aviso_homonimo(monkeypatch):
    monkeypatch.setenv("PORTAL_TRANSPARENCIA_KEY", "x")
    bs._cache = {}
    async def fake_get(client, endpoint, params, chave):
        assert params.get("cpf")
        return (True, [{"nome": "X", "descricaoFuncao": "Secretário"}], "")
    monkeypatch.setattr(bs, "_get", fake_get)
    monkeypatch.setattr(bs, "_salva_cache", lambda: None)
    out = _run(bs.verificar_pep(cpf="11144477735"))
    assert out["eh_pep"] is True and out["motivo"] == ""  # por CPF não há aviso de homônimo
