# -*- coding: utf-8 -*-
"""Testes da Onda 11 (higiene): consolidação de memória do ecossistema."""
from __future__ import annotations


def test_memoria_consolida_fontes():
    from compliance_agent.memoria import consolidar
    r = consolidar(5)
    assert r["ok"] is True
    assert "massare_licoes" in r and "lex_base" in r and "hermes" in r
    assert isinstance(r["_fontes"], list)


def test_memoria_honesta_fonte_ausente(monkeypatch):
    """Fonte indisponível vira nota, nunca quebra nem fabrica."""
    import sys
    monkeypatch.setitem(sys.modules, "massare.learning", None)
    from compliance_agent.memoria import consolidar
    r = consolidar()
    assert r["ok"] is True  # não quebra


def test_capability_memoria_pronto():
    from compliance_agent.skilltree import SkillTree
    st = SkillTree(); st.reload()
    cap = st.capacidades.get("memoria")
    assert cap is not None and cap["status"] == "PRONTO" and cap["rota"] == "/api/memoria"
    assert st.validate() == []
