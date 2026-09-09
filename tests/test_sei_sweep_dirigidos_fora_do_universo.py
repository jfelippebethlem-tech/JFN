# -*- coding: utf-8 -*-
"""Processo enfileirado à mão (hipótese do vault) SEM OB no SIAFE tem de entrar na fila do sweep."""
from __future__ import annotations

from tools.sei_sweep import _incluir_dirigidos_fora_do_universo

_ROWS = [("SEI-040047/001174/2023", 36, 2415045300.0), ("SEI-080002/010538/2024", 3, 3300000.0)]


def test_dirigido_sem_ob_entra_no_fim_com_zero():
    out = _incluir_dirigidos_fora_do_universo(_ROWS, {"SEI-080001/000803/2021"}, filtrado=False)
    assert out[-1] == ("SEI-080001/000803/2021", 0, 0.0) and len(out) == 3


def test_dirigido_que_ja_tem_ob_nao_duplica():
    out = _incluir_dirigidos_fora_do_universo(_ROWS, {"SEI-080002/010538/2024"}, filtrado=False)
    assert out == _ROWS


def test_com_filtro_de_ug_ou_cnpj_nada_entra():
    assert _incluir_dirigidos_fora_do_universo(_ROWS, {"SEI-510001/001163/2025"}, filtrado=True) == _ROWS


def test_lixo_sem_prefixo_sei_fica_de_fora():
    assert _incluir_dirigidos_fora_do_universo(_ROWS, {"080001/000803/2021"}, filtrado=False) == _ROWS
