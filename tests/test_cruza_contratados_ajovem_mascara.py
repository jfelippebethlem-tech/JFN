# -*- coding: utf-8 -*-
"""CPF dos contratados do Ambiente Jovem sai no padrão PAD-04 da casa (`cpf_cnpj.mascarar_cpf`).

A máscara local dava `***456789**` — mesma janela 4–9, mas sem a pontuação do PAD-04, e o dossiê da
Emendatio exibia só os 4 últimos caracteres dela. CPF sintético: nenhum dado real em teste.
"""
from compliance_agent.cpf_cnpj import mascarar_cpf
from tools.cruza_contratados_ajovem import mask

_SINTETICO = "000.111.222-33"


def test_mascara_e_a_regua_unica_pad04():
    assert mask(_SINTETICO) == mascarar_cpf(_SINTETICO) == "***.111.222-**"


def test_mascara_nao_aceita_documento_sem_11_digitos():
    assert mask("") == "***" and mask(None) == "***" and mask("1234") == "***"


def test_mascara_nunca_devolve_os_digitos_fora_da_janela():
    m = mask(_SINTETICO)
    assert "000" not in m.replace("***", "") and not m.endswith("33")
