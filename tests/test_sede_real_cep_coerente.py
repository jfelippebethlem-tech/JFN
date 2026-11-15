# -*- coding: utf-8 -*-
"""CEP × logradouro declarado — validador que existia em `geo.sede_real` e nunca tinha rodado.

Rodado em 14/11/2026 no conjunto de controle de fachada (51 empresas): 10 "incoerentes", e 6 delas eram
DEFEITO DE COMPARAÇÃO, não endereço falso — preposição, abreviação, hífen e complemento no ViaCEP.
Casos reais (declarado na Receita × ViaCEP):
"""
from __future__ import annotations

import pytest

from compliance_agent.geo.sede_real import _cep_confere


def _p(logradouro, cep="24738295", municipio="6001"):
    return {"logradouro": logradouro, "cep": cep, "municipio": municipio}


@pytest.mark.parametrize("declarado,viacep", [
    ("ESTRADA DA MEIA NOITE", "Rua Estrada Meia Noite"),            # 12.768.193/0001-04
    ("AVENIDA BONSUCESSO", "Estrada de Bonsucesso"),                # 01.276.594/0001-20
    ("RODOVIA BR 040", "Rodovia BR-040"),                           # 08.816.020/0001-47
    ("RUA DR. NILO PECANHA", "Rua Doutor Nilo Peçanha"),            # 59.761.132/0001-89
    ("SETOR SCS QD. 08 BLOCO B", "SCS Quadra 8 Bloco B Lotes 50/60"),  # 11.777.162/0001-57
    ("ESPLANADA DOS MINISTERIOS", "Esplanada dos Ministérios Bloco P"),  # 00.394.460/0058-87
])
def test_mesmo_logradouro_escrito_diferente_confere(declarado, viacep):
    assert _cep_confere(_p(declarado), {"logradouro": viacep, "localidade": "X"}) is True


@pytest.mark.parametrize("declarado,viacep", [
    ("RUA OESTE", "Rua Antônio Melo"),                              # 00.775.241/0001-02
    ("VIA CYRINEU TONOLLI", "Rua Emília Muraro Vanini"),            # 00.264.588/0001-90
])
def test_logradouro_diferente_nao_confere(declarado, viacep):
    assert _cep_confere(_p(declarado), {"logradouro": viacep, "localidade": "X"}) is False


def test_cep_generico_nao_julga():
    assert _cep_confere(_p("RUA X", cep="28300000"), {"logradouro": "Rua Y"}) is None


def test_municipio_por_codigo_nao_torna_tudo_coerente():
    """`municipio` na base da Receita é CÓDIGO ('6001'): comparar com o nome nunca deve absolver."""
    assert _cep_confere(_p("RUA OESTE", municipio="Nova Iguaçu"),
                        {"logradouro": "Rua Antônio Melo", "localidade": "Nova Iguaçu"}) is False
