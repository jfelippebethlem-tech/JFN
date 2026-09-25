# -*- coding: utf-8 -*-
"""O MESMO evento, contado duas vezes — e o X7 chamando isso de "dupla correção".

O texto que chega a `extrair_aditivos` é a CONCATENAÇÃO dos documentos de contrato/aditivo do
processo, e a mesma frase costuma aparecer em mais de um: o despacho que relata o aditivo, a
publicação que o extrata, o parecer que o cita.

Medido em 2026-08-05 no **SEI-070002/001289/2022, o processo de MAIOR score do acervo (90,2)**:
das 6 "recomposições" que sustentavam o X7 **crítico**, duas eram a mesma frase — *"Em 19/12/2025,
foi celebrado o 1º Termo Aditivo ao contrato, que promoveu o reequilíbrio econômico-financeiro"* —
repetida em dois documentos. Contar o mesmo fato duas vezes infla a reiteração e pode **inventar**
a dupla correção, que é justamente ver mais de uma recomposição no mesmo exercício.
"""
from __future__ import annotations

from compliance_agent.execucao_fatos import extrair_aditivos

FRASE = ("Em 19/12/2025, foi celebrado o 1º Termo Aditivo ao contrato, que promoveu o "
         "reequilíbrio econômico-financeiro e alterações quantitativas do objeto.")


def test_mesma_frase_em_dois_documentos_conta_uma_vez():
    um = extrair_aditivos(FRASE)
    dois = extrair_aditivos(FRASE + "\n\n" + FRASE)
    assert len(um) == 1, "cenário mal montado: a frase tem de ser extraída como aditivo"
    assert len(dois) == 1, "o mesmo evento repetido em dois documentos virava dois aditivos"


def test_eventos_distintos_na_mesma_data_continuam_distintos():
    """A chave inclui a frase: dois aditivos de datas iguais e conteúdos diferentes são dois."""
    outro = ("Em 19/12/2025, foi celebrado o 2º Termo Aditivo ao contrato, que prorrogou o prazo "
             "de vigência por 12 meses.")
    assert len(extrair_aditivos(FRASE + "\n\n" + outro)) == 2
