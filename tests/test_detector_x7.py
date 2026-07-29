# -*- coding: utf-8 -*-
"""X7 · contrato mínimo do card — o par de topo dos demais `test_detector_x*.py`.

A bateria completa (cinco testes objetivos, rubrica de álea, grounding) vive em
`tests/detectores/test_x7_reequilibrio.py`. Aqui fica o que a catraca
`test_todo_detector_tem_teste` cobra de todo card: a classe exercitada por nome, com contexto
mínimo, provando que ela responde e degrada honesto.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.x7_reequilibrio_indevido import X7ReequilibrioIndevido

DET = X7ReequilibrioIndevido()


def test_identidade_do_card():
    assert DET.id == "X7" and DET.familia == "execucao"
    assert DET.peso() == pytest.approx(0.8)


def test_contexto_vazio_degrada_honesto():
    r = DET.avaliar({"processo": "P-1"})
    assert r.detector == "X7" and r.status == "nao_avaliavel" and r.score == 0.0


def test_recomposicao_acima_do_teto_do_acrescimo_confirma():
    r = DET.avaliar({"processo": "P-1", "valor_inicial": 1_000_000.0,
                     "aditivos": [{"tipo": "reajuste", "valor": 400_000.0,
                                   "data": "2024-01-01"}]})
    assert r.status == "confirmado" and r.score > 0
    assert r.evidencia and r.explicacao_inocente
