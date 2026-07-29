# -*- coding: utf-8 -*-
"""X12 · contrato mínimo do card. Bateria completa em
`tests/detectores/test_x12_benford_quantitativos.py`."""
from __future__ import annotations

import pytest

from compliance_agent.detectores.x12_benford_quantitativos import X12BenfordQuantitativos

DET = X12BenfordQuantitativos()


def test_identidade_do_card():
    assert DET.id == "X12" and DET.familia == "execucao"
    assert DET.peso() == pytest.approx(0.8)


def test_contexto_vazio_degrada_honesto():
    r = DET.avaliar({"processo": "P-1"})
    assert r.detector == "X12" and r.status == "nao_avaliavel" and r.score == 0.0


def test_planilha_artificial_confirma():
    r = DET.avaliar({"processo": "P-1",
                     "itens": [{"quantidade": 100.0} for _ in range(500)]
                              + [{"quantidade": 500.0} for _ in range(500)]})
    assert r.status == "confirmado" and r.score > 0 and r.evidencia
