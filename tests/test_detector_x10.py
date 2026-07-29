# -*- coding: utf-8 -*-
"""X10 · contrato mínimo do card. Bateria completa em
`tests/detectores/test_x10_aditivo_desinstruido.py`."""
from __future__ import annotations

import pytest

from compliance_agent.detectores.x10_aditivo_desinstruido import X10AditivoDesinstruido

DET = X10AditivoDesinstruido()


def test_identidade_do_card():
    assert DET.id == "X10" and DET.familia == "execucao"
    assert DET.peso() == pytest.approx(0.8)


def test_contexto_vazio_degrada_honesto():
    r = DET.avaliar({"processo": "P-1"})
    assert r.detector == "X10" and r.status == "nao_avaliavel" and r.score == 0.0


def test_falta_de_instrucao_confirma():
    r = DET.avaliar({"processo": "P-1", "instrucao": {
        "parecer_juridico": "ausente_declarado", "justificativa_tecnica": "ausente_declarado"}})
    assert r.status == "confirmado" and r.score > 0 and r.evidencia
