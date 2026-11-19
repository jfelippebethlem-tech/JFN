"""Padrão beneficio_para_conta_do_orgao — OB real do Cartão Recomeçar (positivo) e destino privado (negativo)."""
from compliance_agent.padroes import beneficio_para_conta_do_orgao as B

OB = """Ordem Bancária Orçamentária
Emissão
05/03/24
Valor
16.194.000,00
Nota Liquidação
2024NL00101
Credor
CG0013218 - Programa Recomeçar - Municípios do  ERJ
Natureza
339048 - Outros Auxílios Financeiros a Pessoas Físicas
Domicílio Bancário Origem
237 - 6898 - 0000000027 - CONTA ÚNICA
Domicílio Bancário Destino
237 - 6898 - 51322 (28165513000171)
2024OB00221
"""


def test_controle_positivo_le_ob():
    o = B.ler_ob(OB)
    assert o["destino_cnpj"] == "28165513000171" and o["natureza"].startswith("339048") and o["valor"] == 16194000.0
    assert B.grau("1023") == "forte"


def test_negativo_credor_cnpj_privado_nao_e_padrao():
    assert B.ler_ob(OB.replace("CG0013218 - Programa Recomeçar - Municípios do  ERJ", "12345678000199 - EMPRESA X")) is None


def test_negativo_destino_privado_e_municipal():
    assert B.grau("2062") is None and B.grau(None) is None
    assert B.grau("1244") == "medio"


def test_negativo_natureza_que_nao_e_beneficio():
    assert B.ler_ob(OB.replace("339048 - Outros Auxílios", "339039 - Outros Serviços")) is None
