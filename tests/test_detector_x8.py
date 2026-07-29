# -*- coding: utf-8 -*-
"""X8 · contrato mínimo do card — par de topo dos demais `test_detector_x*.py`.

A bateria completa está em `tests/detectores/test_x8_aditivo_retroativo.py`. Aqui fica o que a
catraca `test_todo_detector_tem_teste` cobra: a classe exercitada por nome, com contexto mínimo.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.x8_aditivo_retroativo import X8AditivoRetroativo

DET = X8AditivoRetroativo()


def test_identidade_do_card():
    assert DET.id == "X8" and DET.familia == "execucao"
    assert DET.peso() == pytest.approx(0.8)


def test_contexto_vazio_degrada_honesto():
    r = DET.avaliar({"processo": "P-1"})
    assert r.detector == "X8" and r.status == "nao_avaliavel" and r.score == 0.0


def test_termo_assinado_apos_a_vigencia_confirma():
    r = DET.avaliar({"processo": "P-1", "vigencia_fim": "2024-12-31",
                     "aditivos": [{"data_assinatura": "2025-06-01"}]})
    assert r.status == "confirmado" and r.score > 0 and r.evidencia
