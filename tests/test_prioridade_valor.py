# -*- coding: utf-8 -*-
"""prioridade_valor — interseção RADAR × ECONOMIA (fila priorizada por R$ em risco)."""
from __future__ import annotations

import compliance_agent.cruzamentos_intel as CI


def _fake_radar(db_path=None, limite=100_000):
    return {"achados": [
        {"cnpj": "11111111000111", "cnpj_fmt": "11.111.111/0001-11", "nome": "ARRISCADA RICA",
         "score": 35, "rating": "🟡", "n_sinais": 2, "sinais": [{"sinal": "sancao_a_epoca"}, {"sinal": "fantasma_medio"}]},
        {"cnpj": "22222222000122", "cnpj_fmt": "22.222.222/0001-22", "nome": "FRACA MAS CARA",
         "score": 10, "rating": "🟢", "n_sinais": 1, "sinais": [{"sinal": "sancao_fora_vigencia"}]},
        {"cnpj": "33333333000133", "cnpj_fmt": "33.333.333/0001-33", "nome": "SO RISCO SEM ECONOMIA",
         "score": 50, "rating": "🔴", "n_sinais": 3, "sinais": [{"sinal": "conluio_forte"}]},
    ]}


def _fake_eco(db_path=None, limite=100_000):
    return {"por_fornecedor": [
        {"fornecedor_cnpj": "11111111000111", "fornecedor": "ARRISCADA", "economia": 55_000.0, "n": 2},
        {"fornecedor_cnpj": "22222222000122", "fornecedor": "FRACA", "economia": 239_000.0, "n": 8},
        {"fornecedor_cnpj": "99999999000199", "fornecedor": "SO ECONOMIA SEM RISCO", "economia": 500_000.0, "n": 4},
    ]}


def test_intersecao_ordena_por_economia(monkeypatch):
    monkeypatch.setattr(CI, "radar_risco", _fake_radar)
    monkeypatch.setattr("compliance_agent.comparador_precos.economia_potencial", _fake_eco)
    d = CI.prioridade_valor()
    assert d["ok"] is True and d["n"] == 2                      # só os 2 que estão nas DUAS fontes
    assert d["achados"][0]["cnpj"] == "22222222000122"          # maior economia primeiro
    assert d["achados"][0]["economia"] == 239_000.0
    assert d["achados"][1]["cnpj"] == "11111111000111"
    assert d["economia_em_risco"] == 294_000.0


def test_so_risco_e_so_economia_ficam_de_fora(monkeypatch):
    monkeypatch.setattr(CI, "radar_risco", _fake_radar)
    monkeypatch.setattr("compliance_agent.comparador_precos.economia_potencial", _fake_eco)
    cnpjs = {a["cnpj"] for a in CI.prioridade_valor()["achados"]}
    assert "33333333000133" not in cnpjs   # risco alto mas sem economia → fora
    assert "99999999000199" not in cnpjs   # economia alta mas sem sinal de risco → fora


def test_min_score_filtra(monkeypatch):
    monkeypatch.setattr(CI, "radar_risco", _fake_radar)
    monkeypatch.setattr("compliance_agent.comparador_precos.economia_potencial", _fake_eco)
    d = CI.prioridade_valor(min_score=25)
    cnpjs = {a["cnpj"] for a in d["achados"]}
    assert cnpjs == {"11111111000111"}     # score 10 da FRACA cai fora com piso 25


def test_ressalva_honesta(monkeypatch):
    monkeypatch.setattr(CI, "radar_risco", _fake_radar)
    monkeypatch.setattr("compliance_agent.comparador_precos.economia_potencial", _fake_eco)
    d = CI.prioridade_valor()
    assert "teto teórico" in d["ressalva"] and "Indício ≠ acusação" in d["ressalva"]
    assert "não valor a ressarcir" in d["ressalva"]
