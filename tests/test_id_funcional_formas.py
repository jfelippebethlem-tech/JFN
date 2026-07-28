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


def test_entidade_html_crua_nao_impede_a_extracao():
    """O acervo tem texto com entidade HTML não decodificada: "Subsecret&aacute;rio" em vez de
    "Subsecretário". Medido em 2026-07-28 numa amostra de 300 processos: 5 processos, 45
    arquivos, 727 ocorrências — pouco em volume, mas concentrado em despacho e portaria, que é
    onde os responsáveis são nomeados."""
    from compliance_agent.sei.agentes_publicos import montar_ficha

    docs = {"009_despacho.txt": "Jo&atilde;o Carlos Souza Junior\n"
                                "Subsecret&aacute;rio do Fundo Estadual de Sa&uacute;de\n"
                                "Ordenador de Despesas\nID: 1012634-1"}
    ficha = montar_ficha("080001_003535_2025", docs)
    assert ficha.agentes, "o agente sumiu por causa da entidade HTML"
    ids = {a.id_funcional for a in ficha.agentes}
    assert "1012634-1" in ids


def test_linha_de_identificador_nao_vira_cargo():
    """Medido em 2026-07-28: 15 de 73 cargos preenchidos (20%) eram "ID Funcional nº ...".
    No bloco de assinatura a linha do ID vem logo abaixo do nome, exatamente onde o cargo
    costuma estar — e o parecer saía atribuindo ao servidor o "cargo" de ter um ID."""
    from compliance_agent.sei.agentes_publicos import _e_identificador

    for linha in ("ID Funcional nº 5117607-6", "ID. 51212412", "ID.: 5143252-8",
                  "Matrícula 27.646-9", "IDENTIFICAÇÃO FUNCIONAL 5149448-5"):
        assert _e_identificador(linha) is True, f"{linha!r} devia ser reconhecido como ID"

    for linha in ("Subsecretário de Logística", "Chefe de Serviço de Empenho",
                  "Assistente Executivo - COOFIC/SUPIE", "Fiscal do Contrato"):
        assert _e_identificador(linha) is False, f"{linha!r} é cargo de verdade"
