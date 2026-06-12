# -*- coding: utf-8 -*-
"""Teste da seção 1-D (doações eleitorais TSE × contratos = conflito doador↔contrato) do fornecedor."""
from compliance_agent.reporting import inteligencia as ig


def test_doacoes_indicio_com_tabela():
    ctx = {"cnpj": "11111111000111", "conflito_rede": [
        {"doador": "ALFA LTDA", "via": "empresa", "candidato": "FULANO", "partido": "XX", "ano": 2022,
         "valor_doacao": 50000.0, "ugs": [{"nome": "SES", "total": 1000000.0}], "seis": ["SEI-1", "SEI-2"]}]}
    md = ig._render_doacoes_tse(ctx)
    assert "## 1-D." in md and "CONFLITO DOADOR" in md
    assert "ALFA LTDA" in md and "FULANO" in md and "SES" in md and "SEI-1" in md
    assert "conflito de interesse" in md.lower()


def test_doacoes_vazio_indisponivel():
    md = ig._render_doacoes_tse({"cnpj": "x", "conflito_rede": []})
    assert "## 1-D." in md and "INDISPONÍVEL" in md


def test_doacoes_rede_dict():
    # aceita tanto lista quanto {rede:[...]} (robustez ao formato do lex_conflito)
    ctx = {"cnpj": "x", "conflito_rede": {"rede": [
        {"doador": "BETA", "via": "sócio", "candidato": "X", "partido": "Y", "ano": 2020,
         "valor_doacao": 1000.0, "ugs": [], "seis": []}]}}
    md = ig._render_doacoes_tse(ctx)
    assert "BETA" in md
