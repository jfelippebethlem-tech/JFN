# -*- coding: utf-8 -*-
"""354 processos declaravam documento AUSENTE nos autos, e ninguém lia.

O campo `o_que_falta` da leitura interpretativa existia, custava chamada de IA e morria no banco:
nem a rota o devolvia, nem o painel o mostrava. É a família "achado sem leitor" que esta casa já
documentou seis vezes.

O valor é alto porque boa parte vem do CHECKLIST DO PRÓPRIO ÓRGÃO — ele declara que `Cópia do
Contrato`, `Folha de Medição dos Serviços` e `Relatório dos Fiscais` não estão nos autos. Documento
que PROVA EXECUÇÃO faltando num processo de PAGAMENTO é exatamente a lacuna que sustenta o caso dos
TACs da FSERJ.

E a decisão de QUEM lê isso veio do placar, não de gosto: tentei extrair o checklist por regex e
falhei duas vezes (versão frouxa pegou 32 processos com ruído do tipo `SIM ( X )`; a apertada, 1).
A LLM já lia certo — ela devolve os itens nominalmente. Régua é melhor em número de instrumento;
LLM é melhor em conteúdo interpretativo, e este campo é interpretativo.
"""
from __future__ import annotations

from rotas.vinculos import _falta


def test_lista_vem_como_lista():
    assert _falta(["Cópia do Contrato", "Folha de Medição dos Serviços"]) == [
        "Cópia do Contrato", "Folha de Medição dos Serviços"]


def test_frase_NUMERADA_nao_vira_lista_de_numeros():
    """O primeiro agregado saiu com `1`, `2`, `3` no topo: quebrar em `". "` transformava o
    enumerador em nome de documento. Quebrar NO enumerador resolve."""
    r = _falta("1. Cópia do Contrato assinado 2. Folha de Medição dos Serviços prestados")
    assert r == ["Cópia do Contrato assinado", "Folha de Medição dos Serviços prestados"]
    assert not any(x.strip().isdigit() for x in r)


def test_fragmento_curto_demais_nao_entra():
    """`SIM ( X )` e sobras de tabela não são nome de documento."""
    assert _falta("1. SIM 2. X 3. Relatório dos Fiscais da execução") == [
        "Relatório dos Fiscais da execução"]


def test_vazio_e_ausente_devolvem_lista_vazia():
    for v in (None, "", "[]", "None", []):
        assert _falta(v) == []
