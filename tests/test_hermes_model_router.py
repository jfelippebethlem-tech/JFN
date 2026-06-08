# -*- coding: utf-8 -*-
"""Onda 1 — roteador adaptativo do Hermes: chat trivial fica no free default; caso difícil escala."""
from tools.hermes_model_router import escolher_modelo, DEFAULT, PESADO


def test_chat_trivial_fica_no_default_free():
    assert escolher_modelo("oi, tudo bem?") == DEFAULT
    assert escolher_modelo("bom dia") == DEFAULT


def test_caso_dificil_escala():
    assert escolher_modelo("faça um parecer jurídico sobre esse edital") == PESADO
    assert escolher_modelo("tem sobrepreço nesse contrato?") == PESADO
    assert escolher_modelo("monte um dossiê e investigue o cartel") == PESADO
    assert escolher_modelo("analise à luz da Lei 14.133") == PESADO


def test_mensagem_longa_escala():
    assert escolher_modelo("x" * 700) == PESADO


def test_forcar_pesado():
    assert escolher_modelo("oi", forcar_pesado=True) == PESADO
