# -*- coding: utf-8 -*-
"""Gradeador epistemológico — editais/flags.py. A invariante central: LLM nunca produz flag A.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/editais/test_flags.py -q
"""
from __future__ import annotations

import pytest

from compliance_agent.editais.flags import grau_flag


def test_teste_violado_e_flag_certo():
    r = grau_flag(origem="deterministico", teste_status="violado")
    assert r["grau"] == "A" and r["pode_fundamentar_peca"] is True


def test_llm_nunca_produz_A_mesmo_com_score_maximo():
    r = grau_flag(origem="llm", score=1.0)
    assert r["grau"] == "C" and r["pode_fundamentar_peca"] is False


def test_llm_corroborado_promove_a_B_nunca_A():
    r = grau_flag(origem="llm", score=0.9, familias_convergentes=2)
    assert r["grau"] == "B"


def test_deterministico_forte_convergente_e_B():
    r = grau_flag(origem="deterministico", score=0.85, familias_convergentes=1)
    assert r["grau"] == "B" and r["pode_fundamentar_peca"] is True


def test_deterministico_isolado_e_suspeito():
    assert grau_flag(origem="deterministico", score=0.6)["grau"] == "C"


def test_dentro_do_teto_excupa():
    r = grau_flag(origem="deterministico", teste_status="dentro_do_teto", score=0.9)
    assert r["grau"] == "E" and r["pode_fundamentar_peca"] is False


def test_indisponivel_nao_e_zero():
    r = grau_flag(origem="deterministico", teste_status="nao_aferivel")
    assert r["grau"] == "D"


def test_llm_sem_score_degrada_honesto():
    assert grau_flag(origem="llm")["grau"] == "D"


def test_origem_invalida_explode():
    with pytest.raises(ValueError):
        grau_flag(origem="oraculo")
