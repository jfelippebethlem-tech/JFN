# -*- coding: utf-8 -*-
"""X9 · contrato mínimo do card. A bateria completa está em
`tests/detectores/test_x9_supressao_abusiva.py`; aqui fica o que a catraca
`test_todo_detector_tem_teste` cobra: a classe exercitada por nome."""
from __future__ import annotations

import pytest

from compliance_agent.detectores.x9_supressao_abusiva import X9SupressaoAbusiva

DET = X9SupressaoAbusiva()


def test_identidade_do_card():
    assert DET.id == "X9" and DET.familia == "execucao"
    assert DET.peso() == pytest.approx(0.8)


def test_contexto_vazio_degrada_honesto():
    r = DET.avaliar({"processo": "P-1"})
    assert r.detector == "X9" and r.status == "nao_avaliavel" and r.score == 0.0


def test_supressao_acima_do_teto_confirma():
    r = DET.avaliar({"processo": "P-1", "valor_inicial": 1_000_000.0,
                     "aditivos": [{"objeto": "supressão de itens", "valor_acrescido": 400_000.0}]})
    assert r.status == "confirmado" and r.score > 0 and r.evidencia
