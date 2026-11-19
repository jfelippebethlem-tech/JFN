# -*- coding: utf-8 -*-
"""mrosc_execucao_igual_limiar — controle positivo (Bem Viver, SEI-280001/000624/2025 doc 60) e negativos reais."""
from compliance_agent.padroes.mrosc_execucao_igual_limiar import avaliar_texto

# Trechos literais do doc 60 (Relatório de Execução Físico e Financeiro 125492864).
POSITIVO = ("Valor total das parcelas pagas: R$ 10.777.457,93. IV. CONCLUSÃO Após a análise financeira realizada, "
            "concluiu-se que houve aplicação adequada da Legislação. O convênio 1090 do Convenente: Núcleo Social Bem "
            "Viver, foi corretamente identificado e avaliado, resultando em um total de R$ 7.005.347,65 o que equivale "
            "a 65% do montante total das parcelas que já foram pagas.")

# Doc 109 do mesmo processo: "mais de 65%" com o valor real — não é o limiar escrito.
NEGATIVO_QUALIFICADO = ("Valor total das parcelas pagas: R$ 20.658.857,05. foi corretamente identificado e avaliado, "
                        "resultando em um total de R$ 13.428.257,08 o que equivale a mais de 65% do montante total das "
                        "parcelas que já foram pagas.")


def test_positivo_valor_e_exatamente_65_por_cento_da_base():
    r = avaliar_texto(POSITIVO)
    assert len(r) == 1 and r[0]["percentual"] == 65.0 and r[0]["base"] == 10777457.93


def test_negativo_mais_de():
    assert avaliar_texto(NEGATIVO_QUALIFICADO) == []


def test_negativo_valor_executado_nao_bate_ao_centavo():
    t = POSITIVO.replace("7.005.347,65", "7.005.512,10")
    assert avaliar_texto(t) == []


def test_negativo_parcela_planejada():
    t = ("Valor global R$ 10.000.000,00. Cronograma de desembolso: a parcela de R$ 1.000.000,00 corresponde a 10% "
         "do valor global.")
    assert avaliar_texto(t) == []
