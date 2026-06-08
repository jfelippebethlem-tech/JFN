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
