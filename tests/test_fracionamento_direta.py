# -*- coding: utf-8 -*-
"""Discriminante final do fracionamento: a contratação era DIRETA?

A fila de fracionamento (1.175 grupos, R$ 301,9 mi materializados) é triagem, não achado. Falta
o discriminante que a transforma em indício: pagamentos fracionados sob contrato LICITADO são
execução normal; sob contratação DIRETA repetida ao mesmo credor, na mesma unidade, é o que o
art. 75 §1º da Lei 14.133/2021 veda.

O cruzamento possível é por FORNECEDOR + EXERCÍCIO. O `processo` do SIAFE é número interno e não
casa com o `sei_norm` do TCE-RJ; e a UNIDADE ficou fora porque as bases a guardam de formas
incompatíveis (TCE-RJ por nome, SIAFE por código), o que zerava o cruzamento.

O invariante que estes testes travam: ausência de registro devolve `None`, NUNCA `False`. Não
achar dispensa não prova que houve licitação — prova apenas que não achamos.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.fracionamento_siafe import fornecedor_teve_direta, normalizar_fornecedor


@pytest.fixture()
def con(tmp_path):
    c = sqlite3.connect(tmp_path / "t.db")
    c.execute("""CREATE TABLE compras_diretas_tcerj (id TEXT, processo TEXT, sei_norm TEXT,
        ano_processo INTEGER, valor REAL, objeto TEXT, afastamento TEXT,
        enquadramento_legal TEXT, unidade TEXT, fornecedor TEXT, item TEXT,
        quantidade TEXT, valor_unitario REAL, ingerido_em TEXT)""")
    c.row_factory = sqlite3.Row
    return c


def _reg(c, **kw):
    base = dict(ano_processo=2025, unidade="133100", fornecedor="ACME SERVICOS LTDA",
                afastamento="Dispensa de Licitação")
    base.update(kw)
    c.execute("INSERT INTO compras_diretas_tcerj (ano_processo, unidade, fornecedor, "
              "afastamento) VALUES (:ano_processo,:unidade,:fornecedor,:afastamento)", base)
    c.commit()


_GRUPO = {"exercicio": 2025, "ug_emitente": "133100", "nome_credor": "ACME SERVICOS LTDA"}


def test_confirma_quando_o_registro_bate(con):
    _reg(con)
    assert fornecedor_teve_direta(con, _GRUPO) is True


def test_sem_registro_devolve_None_e_nunca_False(con):
    """INDISPONÍVEL ≠ negativo. Não achar dispensa não prova que houve licitação."""
    assert fornecedor_teve_direta(con, _GRUPO) is None


def test_tabela_ausente_devolve_None(tmp_path):
    assert fornecedor_teve_direta(sqlite3.connect(tmp_path / "vazio.db"), _GRUPO) is None


def test_casa_apesar_de_sufixo_societario_e_acento(con):
    """'ACME SERVIÇOS LTDA.' e 'ACME SERVICOS S/A' são a mesma empresa para este cruzamento."""
    _reg(con, fornecedor="ACME SERVIÇOS LTDA.")
    assert fornecedor_teve_direta(con, _GRUPO) is True


def test_unidade_nao_entra_na_chave_e_isso_e_deliberado(con):
    """As bases guardam a unidade de formas incompatíveis — TCE-RJ por NOME, SIAFE por CÓDIGO —
    e o mapa disponível cobre 3% das UGs da fila. Com a unidade na chave o cruzamento confirmava
    ZERO de 1.175 grupos. O nome da função (`fornecedor_teve_direta`) declara o que ela responde:
    o fornecedor teve direta no exercício, não que ESTA despesa foi direta."""
    _reg(con, unidade="OUTRA UNIDADE QUALQUER")
    assert fornecedor_teve_direta(con, _GRUPO) is True


def test_nao_confunde_exercicio_diferente(con):
    _reg(con, ano_processo=2019)
    assert fornecedor_teve_direta(con, _GRUPO) is None


def test_nome_vazio_nao_casa_com_tudo(con):
    """Guard contra o pior falso positivo: nome vazio normalizando para '' e casando geral."""
    _reg(con, fornecedor="")
    assert fornecedor_teve_direta(con, {**_GRUPO, "nome_credor": ""}) is None


@pytest.mark.parametrize("a,b", [
    ("ACME SERVICOS LTDA", "Acme Serviços Ltda."),
    ("CONSTRUTORA X S/A", "Construtora X SA"),
    ("BETA COMERCIO EIRELI", "Beta Comercio"),
])
def test_normalizacao_junta_as_grafias(a, b):
    assert normalizar_fornecedor(a) == normalizar_fornecedor(b)
