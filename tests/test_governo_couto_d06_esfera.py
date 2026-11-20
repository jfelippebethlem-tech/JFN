# -*- coding: utf-8 -*-
"""D06 da gestão (aditivo acima de 25%): o contrato é do Executivo do Estado do RJ pela RÉGUA, não pelo nome.

O teste antigo era "o nome do órgão tem ESTADO e não tem MUNIC/PREFEITURA": aceitava a Secretaria de Estado de
qualquer UF e autarquia federal "do Estado do Rio de Janeiro" (20/11/2026 — sem vazamento na base de hoje, mas a
regra não o impedia).
"""
import pytest

from compliance_agent.governo_couto_regras import _executivo_estadual_rj


@pytest.mark.parametrize("controle,orgao,esperado", [
    ("42498600000171-2-000010/2026", "ESTADO DO RIO DE JANEIRO", True),                       # controle positivo
    ("42498600000171-2-000011/2026", "TRIBUNAL DE JUSTICA DO ESTADO DO RIO DE JANEIRO", False),   # outro Poder
    ("42498733000148-2-000012/2026", "MUNICIPIO DE RIO DE JANEIRO", False),                   # Prefeitura
    ("00394452000103-2-000013/2026", "COMANDO DO EXERCITO", False),                           # federal
    ("", "SECRETARIA DE ESTADO DE SAUDE DE SAO PAULO", False),                                # "ESTADO" de outra UF
    ("", "CONSELHO REGIONAL DE MEDICINA VETERINARIA DO ESTADO DO RIO DE JANEIRO", False),     # autarquia federal
    ("", "SECRETARIA DE ESTADO DE SAUDE DO RIO DE JANEIRO", True),                            # nome com marca do RJ
])
def test_executivo_estadual_rj(controle, orgao, esperado):
    assert _executivo_estadual_rj(controle, orgao) is esperado
