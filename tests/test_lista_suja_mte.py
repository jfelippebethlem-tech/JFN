# -*- coding: utf-8 -*-
"""Cadastro de Empregadores (MTE) — extração por CNPJ com nome e data de inclusão (fonte pública, sem API)."""
from __future__ import annotations

from tools.lista_suja_mte import extrair

_TX = ("2022 MG VIABRAS ENGENHARIA EIRELI 00.638.595/0001-05 CANTEIRO DE OBRAS, RUA BARÃO DO SUASSUÍ, "
       "BELO HORIZONTE/MG 12 0151-2/01 25/10/2024 09/04/2025\n"
       "2023 PA FAZENDA BOA VISTA LTDA 12.345.678/0001-90 ZONA RURAL, MARABÁ/PA 7 4110-7/00 01/02/2025 09/04/2025\n")


def test_extrai_cnpj_nome_e_data_de_inclusao():
    itens = extrair(_TX)
    assert [i["cnpj"] for i in itens] == ["00638595000105", "12345678000190"]
    assert itens[0]["nome"] == "VIABRAS ENGENHARIA EIRELI"
    assert itens[0]["inclusao"] == "09/04/2025"
    assert itens[1]["nome"] == "FAZENDA BOA VISTA LTDA"
