# -*- coding: utf-8 -*-
"""obra_renovada_como_continuo — Cobrape (SEI-070002/004386/2024, TA 78/2023)."""
from compliance_agent.padroes.obra_renovada_como_continuo import renovacoes

COBRAPE = ("CLÁUSULA PRIMEIRA: prorrogação do prazo de vigência do Contrato INEA nº 28/2022, relativo à prestação de "
           "serviços contínuos de execução de obras de limpeza e desobstrução de cursos d'água, com fundamento no art. "
           "57, inciso II, da Lei nº 8.666/93.\nCLÁUSULA TERCEIRA: Dá-se ao termo aditivo o valor de R$ 12.550.000,08 "
           "(doze milhões), totalizando o contrato o valor de R$ 25.100.000,16 (vinte e cinco milhões).\n"
           "Documento assinado eletronicamente por X, Presidente, em 30/10/2023, às 10:00")


def test_positivo_renovacao_com_valor_cheio():
    r = renovacoes(COBRAPE)
    assert r and r[0]["razao"] == 1.0 and r[0]["objeto_obra"] and r[0]["data"] == "2023-10-30"


def test_negativo_acrescimo_pontual_nao_e_valor_cheio():
    t = COBRAPE.replace("R$ 12.550.000,08", "R$ 1.000.000,00").replace("R$ 25.100.000,16", "R$ 13.550.000,08")
    assert renovacoes(t) == []


def test_negativo_sem_art_57_ii():
    t = COBRAPE.replace("art. \n57, inciso II", "art. 65").replace("57, inciso II", "65, I").replace(
        "serviços contínuos", "serviços")
    assert renovacoes(t) == []
