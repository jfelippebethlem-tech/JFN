# -*- coding: utf-8 -*-
"""X11 · contrato mínimo do card. Bateria completa em
`tests/detectores/test_x11_objeto_descaracterizado.py`."""
from __future__ import annotations

import pytest

from compliance_agent.detectores.x11_objeto_descaracterizado import X11ObjetoDescaracterizado

DET = X11ObjetoDescaracterizado()


def test_identidade_do_card():
    assert DET.id == "X11" and DET.familia == "execucao"
    assert DET.peso() == pytest.approx(0.8)


def test_contexto_vazio_degrada_honesto():
    r = DET.avaliar({"processo": "P-1"})
    assert r.detector == "X11" and r.status == "nao_avaliavel" and r.score == 0.0


def test_mudanca_de_natureza_confirma():
    r = DET.avaliar({"processo": "P-1",
                     "objeto_contrato": "Execução de obra de construção da escola municipal",
                     "aditivos": [{"descricao_objeto": "Locação de veículos para transporte"}]})
    assert r.status == "confirmado" and r.score > 0 and r.evidencia
