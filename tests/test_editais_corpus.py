# -*- coding: utf-8 -*-
"""T2 — corpus de editais (parte offline)."""
from compliance_agent.editais import corpus


def test_material_servico_predominante():
    itens = [{"materialOuServico": "M"}, {"materialOuServico": "M"}, {"materialOuServico": "S"}]
    assert corpus._material_predominante(itens) == "M"
    assert corpus._material_predominante([]) is None
