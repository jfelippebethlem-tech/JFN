# -*- coding: utf-8 -*-
"""Testes da Onda 2 do JFN 2.0: rota de conflito de interesse (doador TSE ↔ sócio ↔ OB)."""
from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")


def _client():
    from fastapi.testclient import TestClient

    import server

    return TestClient(server.app)


def test_api_conflito_responde_e_honesto():
    """GET /api/conflito responde 200 com {ok, rede, _fonte, _nota} (indício, nunca acusação)."""
    c = _client()
    r = c.get("/api/conflito", params={"limite": 5})
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert isinstance(j.get("rede"), list)
    # honestidade: sempre cita fonte e a ressalva de indício
    assert "TSE" in j.get("_fonte", "")
    assert "INDÍCIO" in j.get("_nota", "") or "INDISPONÍVEL" in j.get("_nota", "")


def test_api_conflito_estrutura_da_rede():
    """Cada item da rede traz via (direto|socio), score e os campos de proveniência."""
    c = _client()
    j = c.get("/api/conflito", params={"limite": 10}).json()
    for item in j.get("rede", []):
        assert item["via"] in ("direto", "socio")
        assert "score" in item and "empresa_cnpj" in item and "total_ob" in item
        assert isinstance(item.get("sinais"), list)


def test_capability_conflito_pronto_no_registro():
    """A capacidade conflito_doador_contrato está PRONTO e a rota existe (contrato único)."""
    from compliance_agent.skilltree import SkillTree

    st = SkillTree()
    st.reload()
    cap = st.capacidades.get("conflito_doador_contrato")
    assert cap is not None and cap["status"] == "PRONTO"
    assert st.validate() == []  # rota PRONTO confirmada em server.py


# ---- PNCP (Onda 2b) — testes determinísticos, SEM rede (mock do _get_consulta) ----

_FAKE_PNCP_ITEM = {
    "numeroControlePNCP": "42441758000105-1-000101/2025",
    "objetoCompra": "Aquisição de material de apoio",
    "valorTotalEstimado": 8173.25,
    "modalidadeNome": "Pregão - Eletrônico",
    "situacaoCompraNome": "Divulgada no PNCP",
    "orgaoEntidade": {"cnpj": "42441758000105", "razaoSocial": "ORGAO TESTE RJ"},
    "unidadeOrgao": {"ufSigla": "RJ", "municipioNome": "Rio de Janeiro", "nomeUnidade": "UNIDADE X"},
    "dataAberturaProposta": "2025-09-23T08:00:00",
    "dataEncerramentoProposta": "2025-10-03T10:00:00",
    "processo": "123/2025",
    "linkSistemaOrigem": "https://exemplo/edital",
}


def test_simplificar_contratacao_shape():
    """_simplificar_contratacao normaliza no contrato {id_pncp,objeto,valor,docs,red_flags}."""
    from compliance_agent.collectors.pncp import _simplificar_contratacao

    s = _simplificar_contratacao(_FAKE_PNCP_ITEM)
    assert s["id_pncp"] == "42441758000105-1-000101/2025"
    assert s["valor"] == 8173.25 and s["uf"] == "RJ"
    assert s["orgao_cnpj"] == "42441758000105"
    assert s["docs"] == [] and s["red_flags"] == []  # preenchidos na Onda 2c


def test_buscar_contratacoes_dedup_e_filtro(monkeypatch):
    """buscar_contratacoes pagina, deduplica por id_pncp e filtra por órgão (sem rede)."""
    import asyncio

    from compliance_agent.collectors import pncp

    async def fake_get(endpoint, params):
        # devolve sempre o mesmo item (testa dedup) numa única página
        return {"data": [_FAKE_PNCP_ITEM], "totalPaginas": 1}

    monkeypatch.setattr(pncp, "_get_consulta", fake_get)
    out = asyncio.run(pncp.buscar_contratacoes(uf="RJ", modalidade=6, max_paginas=2))
    assert len(out) == 1  # dedup por id_pncp apesar de 2 páginas
    # filtro por órgão que não casa => vazio
    vazio = asyncio.run(pncp.buscar_contratacoes(uf="RJ", modalidade=6, orgao_cnpj="00000000000000"))
    assert vazio == []


def test_capability_pncp_pronto():
    """consultar_pncp está PRONTO e a rota /api/pncp existe no server.py."""
    from compliance_agent.skilltree import SkillTree

    st = SkillTree()
    st.reload()
    cap = st.capacidades.get("consultar_pncp")
    assert cap is not None and cap["status"] == "PRONTO" and cap["rota"] == "/api/pncp"
    assert st.validate() == []
