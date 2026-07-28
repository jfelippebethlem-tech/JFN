# -*- coding: utf-8 -*-
"""Formas reais de escrever o ID funcional no acervo — todas elas.

MEDIDO em 2026-07-28 sobre a tabela `agente_processo` (387 agentes extraídos): **317 sem
`id_funcional`, e 128 desses tinham o ID no próprio contexto capturado**. Ou seja, 40% das
ausências não eram ausência — eram falha da régua, que exigia a palavra "funcional" e um "nº".

O ID funcional é o que torna o responsável identificável em peça: sem ele, "João da Silva,
fiscal" não individualiza ninguém num quadro de 200 mil servidores. Cada teste abaixo é uma
grafia contada no acervo.
"""
from __future__ import annotations

import pytest

from compliance_agent.sei.agentes_publicos import _identificadores


@pytest.mark.parametrize("janela,esperado", [
    # a que já funcionava
    ("ID Funcional nº 5098630-9", "5098630-9"),
    # 22 ocorrências: só "ID:" — sem a palavra "funcional"
    ("Fiscal do Contrato ID: 4420972-0", "4420972-0"),
    # 9 ocorrências: ponto depois de Id, e dois-pontos
    ("Gestora de Contrato Id. Funcional: 5143197-1", "5143197-1"),
    # 4 ocorrências: ponto depois de ID, com nº
    ("Assessora da Secretaria de Educação ID. Funcional nº 4420972-0", "4420972-0"),
    # 6 ocorrências: travessão antes
    ("MARIA OLIVEIRA BERNARDINO – ID: 5035784-0", "5035784-0"),
    # variações de espaçamento e caixa
    ("id funcional 5147279-1", "5147279-1"),
    ("IDENTIFICAÇÃO FUNCIONAL Nº 5149448-5", "5149448-5"),
])
def test_formas_reais_de_id_funcional(janela, esperado):
    idf, _mat = _identificadores(janela)
    assert idf == esperado


def test_matricula_continua_separada_do_id():
    """São campos distintos; confundi-los troca a identificação do responsável."""
    idf, mat = _identificadores("Matrícula 27.646-9 ID: 5098630-9")
    assert idf == "5098630-9"
    assert mat and "27" in mat


def test_nao_captura_numero_solto_como_id():
    """Guard anti-falso-positivo: número de processo, CNPJ e valor não são ID funcional."""
    for janela in ("Processo SEI-260007/004415/2025", "CNPJ 11.222.333/0001-44",
                   "valor de R$ 1.504.942,22", "Lei 14.133/2021"):
        idf, _ = _identificadores(janela)
        assert idf is None, f"{janela!r} não devia produzir ID"


def test_cpf_nao_e_confundido_com_id_funcional():
    idf, _ = _identificadores("CPF 123.456.789-00")
    assert idf is None
