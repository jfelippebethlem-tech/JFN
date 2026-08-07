# -*- coding: utf-8 -*-
"""A fila do fiscal precisa CHEGAR ao painel — e chegar com a hierarquia intacta.

O ranking existia há semanas e vivia só como markdown em disco: quem quisesse a prioridade da casa
tinha de abrir um arquivo. É a família "construído, testado, nunca rodado" — o código estava certo
e não virava decisão de fiscalização.

O que estes testes vedam, além da rota existir:

1. **O parser não pode inventar item.** A rota lê a saída do ranking com uma expressão regular; se
   ela casar linha de cabeçalho ou de rodapé, a fila ganha processo que não existe. Cada item tem
   de ter número de processo com a forma de processo.
2. **`so_osint` filtra, não reordena.** O sinal OSINT é indício sobre a EMPRESA; o achado é vício
   lido nos AUTOS. Filtrar é legítimo; promover o indício acima do achado não é.
3. **Fila vazia é resposta honesta, não erro.** Se nenhum processo tem sinal OSINT hoje, a rota
   devolve lista vazia com `ok`, e o painel diz "não observado nesta rodada" — nunca "não existe".
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from server import app

_RX_PROC = re.compile(r"^\d{6}/\d{6}/\d{4}$")


@pytest.fixture(scope="module")
def cli():
    """O cliente entra em CONTEXTO de propósito — sem isso o `startup` não roda.

    Medido em 07/08/2026: `TestClient(app)` sem `with` devolvia 404 no espelho da VM-2 e 200 aqui,
    para a mesma rota e o mesmo código. A diferença não era ambiente nem rota sumida: parte do
    roteamento é montada no ciclo de vida da aplicação, e sem abri-lo o teste media a aplicação
    pela metade. Um 404 assim seria lido como "a rota desapareceu" — a pior forma de falso alarme,
    porque manda procurar defeito onde não há.
    """
    with TestClient(app) as c:
        yield c


def _fila(cli, **q):
    r = cli.get("/api/fiscal/fila", params={"limite": 60, **q})
    if r.status_code == 503:
        pytest.skip("ranking indisponível neste ambiente (acervo parcial)")
    assert r.status_code == 200, r.text
    return r.json()


def test_rota_responde_com_fila(cli):
    d = _fila(cli)
    assert d["ok"] is True
    assert d["total"] == len(d["itens"])
    assert d["regua"], "a régua tem de viajar com a fila: número sem critério não se confere"


def test_parser_nao_inventa_item(cli):
    """Cada linha da fila tem de ser um PROCESSO — cabeçalho e rodapé não podem virar item."""
    for x in _fila(cli)["itens"]:
        assert _RX_PROC.match(x["processo"]), f"não é número de processo: {x['processo']!r}"
        assert x["pontos"] >= 0
        assert x["posicao"] >= 1


def test_ordem_e_decrescente_em_pontos(cli):
    pts = [x["pontos"] for x in _fila(cli)["itens"]]
    assert pts == sorted(pts, reverse=True), "fila fora de ordem não é fila"


def test_so_osint_filtra_e_preserva_a_posicao_original(cli):
    """Filtrar é legítimo; PROMOVER o indício acima do achado lido nos autos não é.

    A posição de cada item vem do ranking completo. Se o filtro reordenasse, um processo com
    sinal OSINT e nenhum vício apareceria como "o primeiro da fila" — exatamente a inversão que a
    régua de pontos existe para impedir.
    """
    todos = _fila(cli)
    so = _fila(cli, so_osint=1)
    assert all(x["osint"] for x in so["itens"])
    if not so["itens"]:
        pytest.skip("nenhum processo com sinal OSINT nesta rodada — ausência é resposta válida")
    pos_original = {x["processo"]: x["posicao"] for x in todos["itens"]}
    for x in so["itens"]:
        if x["processo"] in pos_original:
            assert x["posicao"] == pos_original[x["processo"]], (
                "o filtro renumerou a fila — a posição tem de ser a do ranking completo")


def test_fila_vazia_nao_e_erro(cli):
    """Zero item continua sendo `ok`: o painel precisa distinguir vazio de falha."""
    d = _fila(cli, so_osint=1)
    assert d["ok"] is True
    assert isinstance(d["itens"], list)
