# -*- coding: utf-8 -*-
"""Testes da Onda 3 (motor de risco): Lei de Benford 1º/2º dígito (Nigrini)."""
from __future__ import annotations

import math
import random


def test_esperado_primeiro_soma_1_e_p1():
    from compliance_agent.analysis.benford import esperado_primeiro

    e = esperado_primeiro()
    assert abs(e[1] - 0.30103) < 1e-4  # P(1º dígito = 1)
    assert abs(sum(e.values()) - 1.0) < 1e-9


def test_esperado_segundo_soma_1():
    from compliance_agent.analysis.benford import esperado_segundo

    assert abs(sum(esperado_segundo().values()) - 1.0) < 1e-9


def test_significativos():
    from compliance_agent.analysis.benford import _significativos

    assert _significativos(1250)[0] == "1"[0] and _significativos(1250)[:2] == "12"
    assert _significativos(0.0045)[:2] == "45"
    assert _significativos(0) is None
    assert _significativos("nao") is None


def test_benford_conforme_vs_nao_conforme():
    """Lognormal (Benford) => conformidade alta; uniforme => não conformidade."""
    from compliance_agent.analysis.benford import benford

    random.seed(7)
    log = [10 ** (random.uniform(0, 6)) for _ in range(5000)]
    uni = [random.uniform(1000, 9999) for _ in range(5000)]
    rl, ru = benford(log), benford(uni)
    assert rl["primeiro_digito"]["mad"] < ru["primeiro_digito"]["mad"]
    assert rl["primeiro_digito"]["faixa_nigrini"] == "conformidade alta"
    assert ru["primeiro_digito"]["faixa_nigrini"] == "NÃO CONFORMIDADE"


def test_benford_n_insuficiente_marcado():
    from compliance_agent.analysis.benford import benford

    r = benford([100, 200, 300], min_n=50)
    assert r["suficiente"] is False
    assert str(r["n"]) in r["_nota"]


def test_benford_honesto_sem_dados():
    """Lista vazia não quebra e marca n=0 (não inventa distribuição)."""
    from compliance_agent.analysis.benford import benford

    r = benford([])
    assert r["ok"] is True and r["n"] == 0 and r["suficiente"] is False


# ---- Onda 3b: sobrepreço (R4) — determinístico (mock do coletor de preços) ----

def test_sobrepreco_classificar():
    from compliance_agent.sobrepreco import _classificar

    assert "SOBREPREÇO" in _classificar(63.6)
    assert _classificar(5) == "dentro da faixa usual (até +15%)"
    assert _classificar(-10) == "no/abaixo do referencial"


def test_sobrepreco_com_amostra(monkeypatch):
    """Mediana de referência + % de desvio (mock da API; sem rede)."""
    import asyncio

    from compliance_agent import sobrepreco as S

    async def fake(codigo, servico, max_paginas):
        return [40.0, 45.0, 50.0, 55.0, 60.0]  # mediana 50

    monkeypatch.setattr(S, "_coletar_precos", fake)
    r = asyncio.run(S.sobrepreco(267758, valor_pago=80.0))
    assert r["mediana_ref"] == 50.0 and r["n_amostra"] == 5
    assert r["pct"] == 60.0  # (80-50)/50
    assert "SOBREPREÇO" in r["classificacao"]


def test_sobrepreco_sem_amostra_indisponivel(monkeypatch):
    """Sem amostra => mediana_ref=None e fonte INDISPONÍVEL (nunca fabrica)."""
    import asyncio

    from compliance_agent import sobrepreco as S

    async def vazio(codigo, servico, max_paginas):
        return []

    monkeypatch.setattr(S, "_coletar_precos", vazio)
    r = asyncio.run(S.sobrepreco(150018, valor_pago=100))
    assert r["mediana_ref"] is None and "INDISPONÍVEL" in r["fonte"]


def test_capability_sobrepreco_pronto():
    from compliance_agent.skilltree import SkillTree

    st = SkillTree()
    st.reload()
    cap = st.capacidades.get("sobrepreco")
    assert cap is not None and cap["status"] == "PRONTO" and cap["rota"] == "/api/sobrepreco"
    assert st.validate() == []
