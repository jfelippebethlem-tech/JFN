# -*- coding: utf-8 -*-
"""C3 — âncora Painel de Preços (compras.gov.br dados abertos)."""
import json
from pathlib import Path

from compliance_agent.collectors import precos

FIX = json.loads((Path(__file__).parent / "fixtures" / "contratos" / "painel_preco.json").read_text())


def test_mediana_precos():
    r = precos._mediana_precos(FIX)
    assert r["disponivel"] is True and r["n"] >= 1 and r["mediana"] > 0


def test_mediana_vazia():
    assert precos._mediana_precos({"resultado": []})["disponivel"] is False


def test_norm():
    assert precos._norm("Algodão  Hidrófilo ") == "ALGODAO HIDROFILO"
