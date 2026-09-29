# -*- coding: utf-8 -*-
"""Lex: sócio na folha pública vira achado estrutural graduado pelo ENTE; nome curto pede CPF."""
from __future__ import annotations

from compliance_agent.lex_conflito import achado_socio_agente


def test_sem_socios_nao_ha_achado():
    assert achado_socio_agente([]) is None


def test_socio_da_propria_fserj_e_grave_4():
    a = achado_socio_agente([{"nome": "VANESSA TAVARES MANHAES", "cargo": "DIRETOR ASSISTENCIAL",
                              "vinculo": "CARGO COMISSAO", "orgao": "FUNDACAO SAUDE DO ESTADO DO RIO DE JANEIRO", "origem": "folha_estado"}])
    assert a["rf"] == "DD/SOCIO-AGENTE" and a["grav"] == 4
    assert "própria saúde estadual" in a["obs"] and "nome forte" in a["obs"]


def test_socio_da_ses_e_3_e_outro_orgao_e_2_com_aviso_de_homonimo():
    ses = achado_socio_agente([{"nome": "TURIBIO COELHO LEAL FILHO", "cargo": "MÉDICO", "vinculo": "EFETIVO",
                                "orgao": "SECRETARIA DE ESTADO DE SAUDE", "origem": "folha_estado"}])
    assert ses["grav"] == 3
    pm = achado_socio_agente([{"nome": "MARCOS RIBEIRO", "cargo": "SUBTENENTE PM", "vinculo": "EFETIVO",
                               "orgao": "SECRETARIA DE ESTADO DE POLICIA MILITAR", "origem": "folha_estado"}])
    assert pm["grav"] == 2 and "confirmar CPF" in pm["obs"]
