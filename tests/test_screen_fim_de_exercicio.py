# -*- coding: utf-8 -*-
"""Concentração em nov–dez só vira sinal depois de vetar o que é DESENHO do orçamento público.

Medido em 2026-08-09, logo após recoletar as UGs travadas do SIAFE: sem veto, os cinco primeiros
do ranking eram **Fundos Municipais de Saúde** — repasse intergovernamental concentra-se no fim do
exercício por federalismo fiscal, não por vício. Um screen cujo topo é ruído institucional ensina o
fiscal a desconfiar da lista inteira, que é o oposto do que ele existe para fazer.

O que sobra depois do veto é o que interessa: fornecedor PRIVADO cujo ano inteiro cabe em dois
meses — como a NRTT, com 99,2% de R$ 67,3 mi em nov–dez/2023 e R$ 25,4 mi num único 28/12.

Cuidados que o teste fixa:
· `data_emissao` é TEXTO `DD/MM/AAAA` nesta base — o mês está nas posições 4-5, e ordenar/agrupar
  por ele como data é o erro registrado em `data-emissao-siafe-e-texto`;
· pisos de valor e de contagem: concentração sobre duas OBs é acaso, não padrão;
· só `Contabilizado` — OB cancelada não é pagamento.
"""
from __future__ import annotations

import sqlite3

import pytest

import tools.screen_fim_de_exercicio as S


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, credor TEXT, nome_credor TEXT,"
                " data_emissao TEXT, valor REAL, exercicio INT, status TEXT)")

    def ob(i, credor, nome, dia, mes, valor, status="Contabilizado", ano=2023):
        con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?)",
                    (f"{ano}OB{i:05d}", credor, nome, f"{dia:02d}/{mes:02d}/{ano}", valor, ano, status))

    # privado concentrado: 6 OBs, R$ 12 mi, tudo em dezembro
    for i in range(6):
        ob(i, "36366620000196", "NRTT SOLUCOES", 28, 12, 2_000_000)
    # privado espalhado: 6 OBs, R$ 12 mi, ao longo do ano
    for i, mes in enumerate((2, 4, 6, 8, 10, 12)):
        ob(100 + i, "11111111000191", "ESPALHADA LTDA", 15, mes, 2_000_000)
    # ente público concentrado (deve ser vetado pela natureza)
    for i in range(6):
        ob(200 + i, "10497795000104", "Fundo Municipal De Saude", 20, 12, 5_000_000)
    # pequeno concentrado (abaixo do piso de valor)
    for i in range(6):
        ob(300 + i, "22222222000122", "PEQUENA LTDA", 20, 12, 100_000)
    # cancelada: não pode contar
    ob(400, "33333333000133", "CANCELADA LTDA", 20, 12, 90_000_000, status="Excluído")
    con.commit()
    con.close()

    monkeypatch.setattr(S, "_cadastro", lambda: (
        {"36366620": "2062", "11111111": "2062", "10497795": "1236", "22222222": "2062"},
        {"36366620": "NRTT SOLUCOES", "11111111": "ESPALHADA LTDA",
         "10497795": "FUNDO MUNICIPAL DE SAUDE", "22222222": "PEQUENA LTDA"}))
    return str(p)


def test_pega_o_privado_concentrado(db):
    r = {x["raiz"]: x for x in S.medir(db=db)}
    assert "36366620" in r, "fornecedor privado com 100% em dezembro não foi sinalizado"
    assert r["36366620"]["pct"] == 100.0 and r["36366620"]["obs"] == 6


def test_nao_acusa_quem_espalha_no_ano(db):
    assert "11111111" not in {x["raiz"] for x in S.medir(db=db)}


def test_ente_publico_e_vetado(db):
    """Repasse a fundo municipal concentra em dezembro por DESENHO — vetado pela natureza."""
    assert "10497795" not in {x["raiz"] for x in S.medir(db=db)}, (
        "fundo municipal no topo é o ruído que faz o fiscal largar a lista")


def test_pisos_de_valor_e_de_contagem(db):
    assert "22222222" not in {x["raiz"] for x in S.medir(db=db)}
    assert S.medir(min_obs=99, db=db) == []


def test_ob_cancelada_nao_conta(db):
    assert "33333333" not in {x["raiz"] for x in S.medir(min_valor=1_000_000, db=db)}


def test_mes_sai_do_texto_dd_mm_aaaa(db):
    """`data_emissao` é TEXTO: o mês está nas posições 4-5, não numa função de data."""
    import inspect
    fonte = inspect.getsource(S.medir)
    assert "substr(data_emissao,4,2)" in fonte, (
        "voltou a tratar data_emissao como data — o ORDER BY/strftime cru ordena por DIA")
