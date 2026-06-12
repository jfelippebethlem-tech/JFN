# -*- coding: utf-8 -*-
"""Teste da leitura A8 — capital social × recebido (subcapitalização de fachada) do fornecedor."""
from compliance_agent.reporting import inteligencia as ig


def _md(cap, total):
    return ig._capital_recebido_md({"capital_social": cap}, {"total_geral": total})


def test_indicio_alto():
    md = _md(1000, 1_000_000)  # 1000× >= 200
    assert "ALTO" in md and "indício" in md and "8.429" in md


def test_indicio_medio():
    md = _md(10_000, 600_000)  # 60× (>=50x e >500k, <200x)
    assert "MÉDIO" in md and "indício" in md


def test_sem_indicio():
    md = _md(100_000, 600_000)  # 6×
    assert "sem indício" in md.lower()


def test_capital_nulo_atencao():
    md = _md(0, 1_000_000)
    assert "nulo" in md.lower() or "não informado" in md.lower()


def test_indisponivel_vazio():
    assert ig._capital_recebido_md(None, {"total_geral": 100}) == ""
    assert _md(1000, 0) == ""  # sem recebido


def test_num_brl():
    assert ig._num_brl("1.234,56") == 1234.56 and ig._num_brl(1000) == 1000.0 and ig._num_brl("") is None
