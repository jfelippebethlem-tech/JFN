# -*- coding: utf-8 -*-
"""Onda 3 — cartel c/ QSA: sócios em comum entre concorrentes = concorrência fictícia (indício)."""
from __future__ import annotations

from compliance_agent import grafo_cartel
from compliance_agent.providers.base import Resultado, agora_iso


def _fake_lookup(qsa_por_cnpj):
    def _lk(funcao, **q):
        c = q.get("cnpj")
        socios = qsa_por_cnpj.get(c)
        if socios is None:
            return Resultado(False, None, "registry", agora_iso(), "INDISPONIVEL", "404")
        return Resultado(True, {"socios": socios}, "registry", agora_iso())
    return _lk


def test_socios_compartilhados_detecta_socio_comum(monkeypatch):
    import compliance_agent.providers as P
    qsa = {
        "11111111000111": [{"nome": "Joao da Silva", "doc": "***111222**"}],
        "22222222000122": [{"nome": "JOAO DA SILVA", "doc": "***111222**"}],  # mesmo sócio (concorrente!)
        "33333333000133": [{"nome": "Maria Souza", "doc": "***999888**"}],
    }
    monkeypatch.setattr(P, "lookup", _fake_lookup(qsa))
    out = grafo_cartel.socios_compartilhados(["11111111000111", "22222222000122", "33333333000133"])
    assert out["red_flag"] is True and out["n_socios_comuns"] == 1
    comum = out["socios_compartilhados"][0]
    assert comum["socio"] == "joao da silva" and comum["n"] == 2
    assert set(comum["cnpjs"]) == {"11111111000111", "22222222000122"}


def test_socios_compartilhados_sem_comum(monkeypatch):
    import compliance_agent.providers as P
    qsa = {"11111111000111": [{"nome": "Ana"}], "22222222000122": [{"nome": "Bruno Carvalho"}]}
    monkeypatch.setattr(P, "lookup", _fake_lookup(qsa))
    out = grafo_cartel.socios_compartilhados(["11111111000111", "22222222000122"])
    assert out["red_flag"] is False and out["n_socios_comuns"] == 0


def test_norm_nome():
    assert grafo_cartel._norm_nome("José da Silva-Júnior") == "jose da silva junior"


def test_homonimo_de_cpf_diferente_e_socio_sem_doc_nao_acendem(monkeypatch):
    """19/11/2026 — régua identidade_pessoa: nome igual com CPF mascarado diferente é OUTRA pessoa; nome igual
    sem documento é INDETERMINADO. Nenhum dos dois é sócio em comum."""
    import compliance_agent.providers as P
    qsa = {"11111111000111": [{"nome": "Joao da Silva", "doc": "***111222**"}, {"nome": "Pedro Sem Doc", "doc": ""}],
           "22222222000122": [{"nome": "JOAO DA SILVA", "doc": "***333444**"}, {"nome": "Pedro Sem Doc", "doc": ""}]}
    monkeypatch.setattr(P, "lookup", _fake_lookup(qsa))
    out = grafo_cartel.socios_compartilhados(["11111111000111", "22222222000122"])
    assert out["red_flag"] is False and out["n_socios_comuns"] == 0
    assert out["homonimos_separados"] == 1
    assert [x["selo"] for x in out["indeterminados"]] == ["INDETERMINADO"]
