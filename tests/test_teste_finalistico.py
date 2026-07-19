# -*- coding: utf-8 -*-
"""Teste finalístico EXECUTADO (não só exibido) — compliance_agent/editais/teste_finalistico.py.

O INDICE_CLAUSULA traz o teto legal de cada tipo de cláusula como texto ("capital/PL ≤ 10%…");
este módulo extrai o número exigido NA cláusula e compara ao teto, transformando indício
subjetivo em achado objetivo (violado / dentro_do_teto) — e servindo de guard anti-FP
determinístico ANTES do colegiado LLM. Ausência de número aferível → nao_aferivel (≠ 0).
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_teste_finalistico.py -q
"""
from __future__ import annotations

from compliance_agent.editais.teste_finalistico import avaliar


# ── capital / patrimônio líquido (teto 10% do valor estimado — Súmula TCU 275) ──

def test_capital_percentual_acima_do_teto_viola():
    r = avaliar("capital_patrimonio", "Capital social mínimo de 30% (trinta por cento) do valor estimado.")
    assert r["status"] == "violado"
    assert r["valor_extraido"] == 30.0 and r["teto"] == 10.0


def test_capital_no_teto_fica_dentro():
    r = avaliar("capital_patrimonio", "patrimônio líquido mínimo de 10% do valor estimado da contratação")
    assert r["status"] == "dentro_do_teto"


def test_capital_absoluto_compara_com_valor_estimado():
    # R$ 500.000,00 exigidos sobre estimado de R$ 1.000.000,00 = 50% > 10% → violado
    r = avaliar("capital_patrimonio", "capital social integralizado mínimo de R$ 500.000,00",
                valor_estimado=1_000_000.0)
    assert r["status"] == "violado"
    assert r["valor_extraido"] == 50.0


def test_capital_absoluto_sem_valor_estimado_nao_aferivel():
    r = avaliar("capital_patrimonio", "capital social mínimo de R$ 500.000,00")
    assert r["status"] == "nao_aferivel"


# ── atestado quantitativo (teto 50% do licitado — Súmula TCU 263) ──

def test_atestado_acima_de_50_viola():
    r = avaliar("atestado_quantitativo", "atestado comprovando execução de no mínimo 60% (sessenta por cento) do quantitativo")
    assert r["status"] == "violado" and r["teto"] == 50.0


def test_atestado_dentro_do_teto_rebaixa():
    r = avaliar("atestado_quantitativo", "atestado de no mínimo 40 % do objeto licitado")
    assert r["status"] == "dentro_do_teto"


# ── garantia de proposta (teto 1% — Lei 14.133 art. 58 §1º) ──

def test_garantia_acima_de_1_viola():
    r = avaliar("garantia_proposta", "garantia de proposta de 5% do valor estimado")
    assert r["status"] == "violado"


def test_garantia_de_1_dentro():
    r = avaliar("garantia_proposta", "garantia de manutenção de proposta de 1% (um por cento)")
    assert r["status"] == "dentro_do_teto"


# ── marca dirigida (mitigada pela expressão de equivalência — Súmula TCU 270) ──

def test_marca_com_equivalente_dentro():
    r = avaliar("marca_dirigida", "notebook marca Dell Latitude ou equivalente técnico")
    assert r["status"] == "dentro_do_teto"


def test_marca_similar_tambem_mitiga():
    r = avaliar("marca_dirigida", 'toner original HP "ou similar de qualidade igual ou superior"')
    assert r["status"] == "dentro_do_teto"


def test_marca_sem_equivalencia_viola():
    r = avaliar("marca_dirigida", "será aceito exclusivamente equipamento da marca Cisco modelo X")
    assert r["status"] == "violado"


# ── recorte temporal (prazo exíguo objetivo ≤ 2 dias; acima disso é juízo de proporcionalidade) ──

def test_prazo_24_horas_e_exiguo():
    r = avaliar("recorte_temporal", "apresentação de amostra no prazo de 24 (vinte e quatro) horas")
    assert r["status"] == "violado"


def test_prazo_2_dias_e_exiguo():
    r = avaliar("recorte_temporal", "entrega da amostra em até 2 (dois) dias úteis")
    assert r["status"] == "violado"


def test_prazo_10_dias_nao_aferivel_objetivamente():
    r = avaliar("recorte_temporal", "amostra no prazo de 10 (dez) dias corridos")
    assert r["status"] == "nao_aferivel"
    assert r["valor_extraido"] == 10.0


# ── honestidade / contrato da função ──

def test_subtipo_sem_regra_devolve_none():
    assert avaliar("pontuacao_dirigida", "quesito de pontuação por certificação X") is None


def test_clausula_vazia_nao_aferivel():
    r = avaliar("capital_patrimonio", "")
    assert r["status"] == "nao_aferivel"


def test_resultado_carrega_fonte_do_teto():
    # todo resultado aferido cita a âncora do teto (súmula/dispositivo) — vai para a ficha Kroll
    r = avaliar("atestado_quantitativo", "mínimo de 80% do quantitativo")
    assert "263" in r["fonte_teto"]


# ── quantil interpolado (lex_base_empirica) ──

def test_quantil_interpolado():
    from compliance_agent.lex_base_empirica import _quantil
    vals = list(range(1, 11))          # 1..10
    assert _quantil(vals, 0.5) == 5.5  # mediana interpolada, não truncada
    assert abs(_quantil(vals, 0.9) - 9.1) < 1e-9
    assert _quantil([7], 0.9) == 7.0
    assert _quantil([], 0.5) is None
