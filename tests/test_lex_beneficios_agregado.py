# -*- coding: utf-8 -*-
"""Teste do agregado de benefícios dos sócios/admin (laranja) na seção II-E do parecer Lex. Sem rede."""
from compliance_agent import lex
from compliance_agent.reporting import beneficios_view as bv


def _render(inv, cnpj):
    L = []
    lex._secao_investigacao(L.append, inv, cnpj=cnpj)
    return "\n".join(L)


def test_ii_e_renderiza_sempre():
    md = _render({}, "00000000000000")
    assert "II-E" in md  # a seção existe mesmo sem investigação DD


def test_agregado_indicio(monkeypatch):
    monkeypatch.setattr(bv, "por_fornecedor", lambda c, **k: {
        "n_verificados": 2, "n_com_beneficio": 1, "n_pessoas_beneficio": 1,
        "total_qsa": 3, "n_indisponivel": 1})
    md = _render({}, "123")
    assert "sweep" in md and "interposição de pessoas (laranja)" in md and "INDISPONÍVEL" in md


def test_agregado_afastado(monkeypatch):
    monkeypatch.setattr(bv, "por_fornecedor", lambda c, **k: {
        "n_verificados": 3, "n_com_beneficio": 0, "n_pessoas_beneficio": 0,
        "total_qsa": 5, "n_indisponivel": 2})
    md = _render({}, "123")
    assert "nenhum recebe benefício" in md and "afastado" in md
