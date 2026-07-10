# -*- coding: utf-8 -*-
"""Task 3 — parse e classificação de recorte do coletor de emendas."""
from compliance_agent.emendas import coletor


def test_parse_brl():
    assert coletor.parse_brl("41.161,00") == 41161.0
    assert coletor.parse_brl("") == 0.0
    assert coletor.parse_brl(None) == 0.0


ROSTER = {"LUCIANO VIEIRA"}


def _em(autor="X", loc="CUIABÁ - MT"):
    return {"nomeAutor": autor, "localidadeDoGasto": loc}


def test_classificar_recorte():
    assert coletor.classificar_recorte(_em("LUCIANO VIEIRA", "DUAS BARRAS - RJ"), ROSTER) == "AMBOS"
    assert coletor.classificar_recorte(_em("LUCIANO VIEIRA", "CUIABÁ - MT"), ROSTER) == "AUTOR_RJ"
    assert coletor.classificar_recorte(_em("GENERAL GIRAO", "RIO DE JANEIRO (UF)"), ROSTER) == "DESTINO_RJ"
    assert coletor.classificar_recorte(_em("GENERAL GIRAO", "RIO GRANDE DO NORTE (UF)"), ROSTER) is None


def test_e_pix():
    assert coletor.e_pix("Emenda Individual - Transferências Especiais") == 1
    assert coletor.e_pix("Emenda Individual - Transferências com Finalidade Definida") == 0
