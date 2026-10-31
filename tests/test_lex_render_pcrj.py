# -*- coding: utf-8 -*-
"""Parecer Lex: retrato dos contratos com a Prefeitura do Rio (ContasRio/CCON) na seção II-E (13/09/2026)."""
from __future__ import annotations

from compliance_agent.lex_render import _secao_investigacao


def test_secao_investigacao_mostra_contratos_municipais_com_processo_e_link():
    linhas = []
    inv = {"grau": "🟢", "hipoteses": [], "pcrj_contratos": {
        "n": 12, "diretas": 10, "valor": 5000000.0, "pago": 1234567.89, "n_orgaos": 2, "orgaos": "SMC,RIOFILME",
        "ano_min": 2024, "ano_max": 2026,
        "maiores": [{"ano": 2026, "orgao": "3051 - DISTRIBUIDORA DE FILMES S/A", "forma": "Contratação Direta - Inexigibilidade",
                     "objeto": "Contratação do Festival do Rio 2026", "processo": "006300.000569/2026-14",
                     "url_ccon": "https://siafic-apps-externas.rio.rj.gov.br/ccon-web/?contrato=2611958"}]}}
    _secao_investigacao(linhas.append, inv, "11709793000139")
    txt = "\n".join(linhas)
    assert "Contratos com a Prefeitura do Rio (ContasRio, 2024–2026)" in txt
    assert "12 contrato(s), 10 por contratação direta" in txt and "R$ 1.234.567,89" in txt
    assert "006300.000569/2026-14" in txt and "ccon-web/?contrato=2611958" in txt


def test_sem_contratos_municipais_nada_e_inventado():
    linhas = []
    _secao_investigacao(linhas.append, {"grau": "🟢", "hipoteses": []}, "")
    assert "Prefeitura do Rio (ContasRio" not in "\n".join(linhas)
