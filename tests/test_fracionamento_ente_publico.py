"""Ente publico nao entra em lista de fracionamento — e o filtro e UM so.

Achado em 25/07/2026: 6 dos 63 grupos do detector de fracionamento eram MINISTERIO DA
FAZENDA e INSS. Recolhimento de tributo e previdencia apresentado como compra fatiada,
num relatorio de fiscalizacao.

Causa: havia DUAS copias divergentes do filtro "nao e ente publico" no mesmo arquivo —
uma local dentro de `fracionamento` e a `_SQL_NAO_PUBLICO` "reutilizavel" —, cada uma
excluindo o que a outra nao excluia. Mesma familia do defeito que `limites_dispensa.py`
ja alertava ("NUNCA duplicar esta tabela em detector").

Este teste trava as duas coisas: os federais ficam de fora, e os fornecedores privados de
nome parecido continuam DENTRO (o filtro nao pode ser ganancioso).
"""
import re
import sqlite3

import pytest

from compliance_agent.cruzamentos_intel import _SQL_NAO_PUBLICO

# nomes REAIS colhidos do universo de credores do compliance.db
PUBLICOS = [
    "MINISTÉRIO DA FAZENDA", "MINISTERIO DA ECONOMIA",
    "Instituto Nacional De Seguro Social.", "Instituto Nacional Do Seguro Social",
    "PGE - PROCURADORIA GERAL DO ESTADO", "Controladoria Geral do Estado do Rio de Janeiro",
    "PREFEITURA MUNICIPAL DE NITEROI", "FUNDO MUNICIPAL DE SAUDE",
    "TRIBUNAL DE JUSTICA", "CÂMARA MUNICIPAL",
]
# privados que NAO podem ser varridos junto — o motivo de o filtro ser por nome inteiro
PRIVADOS = [
    "UNIAO QUIMICA FARMACEUTICA NACIONAL S A",
    "Uniao Norte Fluminense Eng. E Comercio Ltda",
    "INSTITUTO DE DESENVOLVIMENTO PARA EDUCAÇÃO, SAÚDE E INTEGRAÇÃO",
    "I.D.E.A.S - INSTITUTO DESENVOLVIMENTO ENSINO E ASSISTENCIA",
    "PLASMA LABORATÓRIO DE ANALISES CLINICAS LTDA",
    "Comercial Milano Brasil Ltda",
]


@pytest.fixture(scope="module")
def banco():
    """Aplica o SQL de verdade — testar a regex à mão não provaria o SQL que roda."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (nome_credor TEXT)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?)",
                    [(n,) for n in PUBLICOS + PRIVADOS])
    return con


def _passa(con) -> set[str]:
    return {r[0] for r in con.execute(
        f"SELECT nome_credor FROM ob_orcamentaria_siafe WHERE {_SQL_NAO_PUBLICO}")}


@pytest.mark.parametrize("nome", PUBLICOS)
def test_ente_publico_fica_de_fora(nome, banco):
    assert nome not in _passa(banco), f"{nome!r} passou pelo filtro e vira falso positivo"


@pytest.mark.parametrize("nome", PRIVADOS)
def test_fornecedor_privado_continua_dentro(nome, banco):
    assert nome in _passa(banco), (
        f"{nome!r} foi varrido junto — filtro ganancioso apaga fornecedor real da fila")


def test_o_filtro_e_um_so_nao_ha_copia_divergente():
    """A cópia local dentro de `fracionamento` foi removida; se voltar, este teste cai."""
    fonte = (__import__("pathlib").Path(__file__).resolve().parents[1]
             / "compliance_agent" / "cruzamentos_intel.py").read_text(encoding="utf-8")
    copias = len(re.findall(r"nome_credor NOT LIKE '%FUNDO%'", fonte))
    assert copias == 1, (
        f"{copias} cópias do filtro de ente público em cruzamentos_intel.py — "
        "elas divergem com o tempo e foi exatamente assim que MINISTÉRIO DA FAZENDA "
        "entrou numa lista de fracionamento")
