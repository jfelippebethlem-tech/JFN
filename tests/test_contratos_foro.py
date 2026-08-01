# -*- coding: utf-8 -*-
"""Foro do parecer de contratos segue a esfera do órgão (Fiocruz→TCU, não TCM-RJ)."""
from compliance_agent.contratos import parecer


def test_foro_federal_fiocruz():
    esfera, foro = parecer.foro_do_contrato("FUNDACAO OSWALDO CRUZ", "33781055000135")
    assert esfera == "federal"
    assert foro == "TCU"


def test_foro_municipal_rio():
    esfera, foro = parecer.foro_do_contrato("MUNICIPIO DO RIO DE JANEIRO", "42498733000148")
    assert esfera == "municipal-rio"
    assert foro == "TCM-RJ"


def test_foro_estadual():
    esfera, foro = parecer.foro_do_contrato("SECRETARIA DE ESTADO DE SAUDE", "42498600000171")
    assert esfera == "estadual-rj"
    assert foro == "TCE-RJ"


def test_foro_indefinido_nao_chuta():
    esfera, foro = parecer.foro_do_contrato("", "")
    assert esfera == "indefinido"
    assert foro == "órgão de controle competente"


def test_voto_usa_foro():
    v = parecer._voto("indício de irregularidade", ["sobrepreco"], foro="TCU")
    assert "TCU" in v and "TCM-RJ" not in v


def test_voto_default_sem_foro_nao_acusa_orgao_errado():
    # sem foro conhecido, o voto aponta o órgão de controle competente, nunca um TC específico
    v = parecer._voto("indício de irregularidade", ["sobrepreco"])
    assert "TCM-RJ" not in v and "competente" in v
