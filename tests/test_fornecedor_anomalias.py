# -*- coding: utf-8 -*-
"""Teste da seção 8-C (anomalias nas OBs, modelo de detecção) do fornecedor. Sem DB: ctx mockado."""
from compliance_agent.reporting import inteligencia as ig


def test_anomalias_indicio():
    ctx = {"anomalias": {"ok": True, "n_obs": 50, "n_anomalas": 3, "modelo": "onda1-v1.0", "itens": [
        {"score": 0.823, "feats": '["log_valor", "forn_freq", "dow"]', "ob": "2020OB04335",
         "valor": 4639266.07, "data": "2020-05-10"}]}}
    md = ig._render_anomalias(ctx)
    assert "## 8-C." in md and "ANOMALIAS" in md
    assert "2020OB04335" in md and "valor atípico" in md  # feature traduzida
    assert "indício" in md.lower() and "não prova" in md.lower()


def test_anomalias_sem_score_alto():
    md = ig._render_anomalias({"anomalias": {"ok": True, "n_obs": 30, "n_anomalas": 0, "itens": []}})
    assert "Nenhuma OB com score alto" in md and "sem anomalia destacada" in md.lower()


def test_anomalias_indisponivel():
    md = ig._render_anomalias({"anomalias": {"ok": False}})
    assert "8-C" in md and "INDISPONÍVEL" in md
