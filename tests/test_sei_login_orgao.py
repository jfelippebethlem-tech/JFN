"""O órgão do login tem de ser escolhível — hoje é fixo em ITERJ.

Causa-raiz (2026-07-23) de o conteúdo cross-unit nunca vir: `sei_reader.login`
seleciona sempre o ITERJ no `#selOrgao`, e o SEI só serve o teor de documentos do
órgão da sessão. Para documento de outro órgão ele devolve a LISTA DE ÓRGÃOS — que
capturávamos como se fosse o documento. Não era negativa de acesso (o itkava enxerga
tudo, ver vault: "SEI acesso liberado — nunca culpar acesso"): era o SEI dizendo
"esse processo é de outro órgão".

Estes testes fixam a ESCOLHA do órgão. Os 18 chamadores existentes não passam órgão
nenhum e têm de continuar caindo no ITERJ — mudança aditiva, zero regressão.
"""
import re

import pytest

from tools.sei_reader import escolher_orgao

_OPCOES = [
    {"v": "0", "t": "Selecione"},
    {"v": "12", "t": "INEA - Instituto Estadual do Ambiente"},
    {"v": "31", "t": "ITERJ - Instituto de Terras e Cartografia"},
    {"v": "44", "t": "SES - Secretaria de Estado de Saúde"},
    {"v": "51", "t": "SEOP - Secretaria de Obras"},
]


def test_sem_pedido_mantem_iterj():
    """Os 18 chamadores atuais não passam órgão — não podem mudar de comportamento."""
    assert escolher_orgao(_OPCOES, None) == "31"
    assert escolher_orgao(_OPCOES, "") == "31"


@pytest.mark.parametrize("pedido,esperado", [
    ("INEA", "12"),
    ("inea", "12"),
    ("SES", "44"),
    ("Secretaria de Estado de Saúde", "44"),
    ("SEOP", "51"),
])
def test_escolhe_o_orgao_pedido(pedido, esperado):
    assert escolher_orgao(_OPCOES, pedido) == esperado


def test_orgao_inexistente_cai_no_padrao_em_vez_de_quebrar():
    """Pedido inválido não pode derrubar o login — degrada para o ITERJ."""
    assert escolher_orgao(_OPCOES, "ORGAO-QUE-NAO-EXISTE") == "31"


def test_sem_iterj_na_lista_devolve_none_em_vez_de_chutar():
    """Sem o padrão disponível, NÃO escolher é mais honesto que escolher errado."""
    opcoes = [{"v": "0", "t": "Selecione"}, {"v": "12", "t": "INEA"}]
    assert escolher_orgao(opcoes, None) is None


def test_nao_confunde_sigla_dentro_de_outra_palavra():
    opcoes = [{"v": "7", "t": "FUNDO ESPECIAL (SESPORT)"}, {"v": "9", "t": "SES - Saúde"},
              {"v": "31", "t": "ITERJ"}]
    assert escolher_orgao(opcoes, "SES") == "9", "SESPORT não é SES"
