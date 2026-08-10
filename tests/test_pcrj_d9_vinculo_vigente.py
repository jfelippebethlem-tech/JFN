# -*- coding: utf-8 -*-
"""Sócio que entrou no quadro DEPOIS da despesa não descreve a despesa.

Medido em 2026-08-10 sobre 209.559 pares (despesa, sócio) do acervo PCRJ: **84.365 (40,3%)** têm o
sócio entrando depois do exercício em que o credor recebeu, com vão de até 7 anos. Mesma lição do
E.3.2, onde o filtro de `data_entrada` derrubou os dois maiores pares da lista.
"""
from __future__ import annotations

import sqlite3

import pytest

import compliance_agent.pcrj.pericia_gastos as P


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
      create table pcrj_despesa (exercicio integer, credor_documento text, credor_nome text,
                                 pago real);
      create table socios_receita (cnpj_basico text, nome_norm text, nome_socio text,
                                   data_entrada text);
    """)
    return c


FOLHA = {"maria da silva souza": {"orgao": "SMS"}}


def _cenario(con, entrada, exercicio=2021):
    con.execute("insert into pcrj_despesa values (?,?,?,?)",
                (exercicio, "11111111000111", "ALFA LTDA", 100000.0))
    con.execute("insert into socios_receita values (?,?,?,?)",
                ("11111111", "maria da silva souza", "MARIA DA SILVA SOUZA", entrada))
    con.commit()
    a = P.d9_socio_na_folha(con, folha_norm=FOLHA)
    assert len(a) == 1
    return a[0]


def test_socio_ja_no_quadro_segue_indicio_normal(con):
    a = _cenario(con, "20190301")
    assert a["evidencias"]["vinculo_posterior"] is False
    assert a["risco"] == 5
    assert a["titulo"].startswith("Sócio de credor na folha")


def test_socio_POSTERIOR_e_rebaixado_e_declarado(con):
    """O caso dos 40,3%: despesa de 2021, sócio entrou em 2024."""
    a = _cenario(con, "20240115")
    assert a["evidencias"]["vinculo_posterior"] is True
    assert a["risco"] == 3
    assert "POSTERIOR" in a["titulo"]
    assert "NÃO descreve a despesa" in a["descricao"]


def test_entrada_no_MESMO_ano_conta_como_vigente(con):
    """Critério conservador: basta ter sido sócio em ALGUM exercício com pagamento — não se derruba
    indício por detalhe de mês."""
    a = _cenario(con, "20211230")
    assert a["evidencias"]["vinculo_posterior"] is False


def test_sem_data_de_entrada_nao_rebaixa(con):
    """Sem data não se afirma posterioridade — INDISPONÍVEL não vira absolvição nem condenação."""
    a = _cenario(con, "")
    assert a["evidencias"]["vinculo_posterior"] is False
    assert a["risco"] == 5


def test_nome_curto_nao_entra(con):
    """Guard anti-homônimo pré-existente: nome com <3 tokens gera ruído em massa."""
    con.execute("insert into pcrj_despesa values (2021,'22222222000122','BETA','1')")
    con.execute("insert into socios_receita values ('22222222','joao silva','JOAO SILVA','20190101')")
    con.commit()
    assert P.d9_socio_na_folha(con, folha_norm={"joao silva": {"orgao": "X"}}) == []
