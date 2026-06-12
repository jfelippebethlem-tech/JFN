# -*- coding: utf-8 -*-
"""Teste da seção 1-E (rodízio de vencedores / cartel) do fornecedor. Sem DuckDB: ctx mockado."""
from compliance_agent.reporting import inteligencia as ig


def test_rodizio_indicio():
    ctx = {"rodizio_forn": {"ok": True, "ugs_avaliadas": 3, "aneis": [
        {"ug": "170100", "score": 74.1, "n_campeoes": 3, "share_ring": 0.8, "n_vitorias": 2, "anos": [2021, 2023]}]}}
    md = ig._render_rodizio_fornecedor(ctx)
    assert "## 1-E." in md and "BID ROTATION" in md
    assert "170100" in md and "indício" in md.lower() and "12.529" in md


def test_rodizio_afastado():
    md = ig._render_rodizio_fornecedor({"rodizio_forn": {"ok": True, "ugs_avaliadas": 2, "aneis": []}})
    assert "nenhum anel" in md and "afastado" in md


def test_rodizio_indisponivel():
    md = ig._render_rodizio_fornecedor({"rodizio_forn": {"ok": False, "ugs_avaliadas": 0, "aneis": []}})
    assert "INDISPONÍVEL" in md


def test_fato_rodizio_no_raciocinio():
    ctx = {"nome": "ALFA", "cnpj_fmt": "x", "cnpj": "11111111000111", "risco": "MÉDIO", "score": 40,
           "pagamentos": {"tem_dados": False},
           "rodizio_forn": {"aneis": [{"ug": "170100"}]}, "beneficios_socios": {}}
    fatos = ig._fatos_para_raciocinio(ctx)
    assert "rodízio" in fatos.lower() and "cartel" in fatos.lower() and "170100" in fatos
