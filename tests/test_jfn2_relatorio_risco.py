# -*- coding: utf-8 -*-
"""Recalibração de risco do /relatorio (fix 2026-06-08): a manchete deve refletir os indícios reais,
nunca ficar 'BAIXO 0' quando há conflito / pago≫contratado / crescimento atípico / concentração."""
from __future__ import annotations

from compliance_agent.reporting.inteligencia import _crescimento, _recalibrar_risco


def _pag(total, anos_vals, top_share=0.0):
    por_ano = {a: {"total": v} for a, v in anos_vals.items()}
    return {"total_geral": total, "anos": list(anos_vals), "por_ano": por_ano, "hhi": {"top_share": top_share}}


def test_crescimento_pico_sobre_base():
    p = _pag(580e6, {2019: 24.7e6, 2025: 188e6})
    assert round(_crescimento(p), 1) == 7.6
    assert _crescimento(_pag(0, {})) == 1.0  # sem dado → neutro


def test_caso_extreme_baixo0_vira_alto():
    """Caso real: externo 0/BAIXO + R$580M + conflito + pago 2,2× + crescimento 7,6× → ALTO."""
    p = _pag(580e6, {2019: 24.7e6, 2025: 188e6}, top_share=24.5)
    cal = _recalibrar_risco(p, rede=[{"x": 1}], contratado_tcerj=259e6, score_ext=0, risco_ext="BAIXO")
    assert cal["risco"] == "ALTO" and cal["score"] >= 70
    assert cal["score_externo"] == 0 and cal["score_interno"] >= 70
    assert any("pago" in s for s in cal["sinais"]) and any("conflito" in s for s in cal["sinais"])


def test_nunca_rebaixa_o_score_externo():
    """Se o externo já é alto, o final NÃO cai (max), mesmo sem sinais internos."""
    p = _pag(1e6, {2024: 1e6}, top_share=10)
    cal = _recalibrar_risco(p, rede=[], contratado_tcerj=0, score_ext=90, risco_ext="ALTO")
    assert cal["score"] == 90


def test_empresa_limpa_continua_baixo():
    """Sem indícios e exposição pequena → BAIXO (não infla risco à toa)."""
    p = _pag(500e3, {2024: 500e3}, top_share=10)
    cal = _recalibrar_risco(p, rede=[], contratado_tcerj=600e3, score_ext=0, risco_ext="BAIXO")
    assert cal["risco"] == "BAIXO" and cal["score"] == 0


def test_pago_muito_acima_do_contratado_pesa():
    p = _pag(300e6, {2024: 300e6}, top_share=10)
    cal = _recalibrar_risco(p, rede=[], contratado_tcerj=100e6, score_ext=0, risco_ext="BAIXO")
    assert any("≫" in s or "pago" in s for s in cal["sinais"]) and cal["score"] >= 25
