# -*- coding: utf-8 -*-
"""Rodízio temporal de cartel — núcleo PURO (sem DB): vencedores que se revezam no #1 da UG ano a ano.

Distingue RODÍZIO (conjunto estreito alternando o topo + dominância) de CONCENTRAÇÃO/dependência
(um só fornecedor sempre no topo) — esta última já é coberta por grafo_cartel.captura/dependencia.
Honesto: OB mostra o VENCEDOR (pagamento), não os licitantes → indício a corroborar (SEI/PNCP)."""
from __future__ import annotations

from compliance_agent import rodizio_temporal as R


def test_rodizio_classico_tres_revezando():
    # A, B, C dominam a UG e se revezam no #1 ano a ano (textbook bid rotation)
    por_ano = {
        2020: [{"cnpj": "A", "nome": "Alfa", "valor": 1000}, {"cnpj": "B", "nome": "Beta", "valor": 200},
               {"cnpj": "C", "nome": "Gama", "valor": 150}],
        2021: [{"cnpj": "B", "nome": "Beta", "valor": 1000}, {"cnpj": "A", "nome": "Alfa", "valor": 180},
               {"cnpj": "C", "nome": "Gama", "valor": 120}],
        2022: [{"cnpj": "C", "nome": "Gama", "valor": 1000}, {"cnpj": "A", "nome": "Alfa", "valor": 160},
               {"cnpj": "B", "nome": "Beta", "valor": 140}],
        2023: [{"cnpj": "A", "nome": "Alfa", "valor": 1000}, {"cnpj": "B", "nome": "Beta", "valor": 190},
               {"cnpj": "C", "nome": "Gama", "valor": 130}],
    }
    r = R._detectar_rodizio(por_ano)
    assert r["indicio"] is True
    assert r["n_anos"] == 4 and r["n_campeoes"] == 3
    assert r["alternancia"] == 1.0          # o #1 trocou de mãos todo ano
    assert r["share_ring"] >= 0.99          # os campeões capturam ~todo o gasto
    # A venceu 2 anos (2020, 2023) → primeiro no ranking de campeões
    assert r["campeoes"][0]["cnpj"] == "A" and r["campeoes"][0]["n_vitorias"] == 2


def test_concentracao_nao_e_rodizio():
    # Um só fornecedor sempre no topo = dependência/captura, NÃO rodízio
    por_ano = {
        2020: [{"cnpj": "A", "nome": "Alfa", "valor": 1000}, {"cnpj": "B", "nome": "Beta", "valor": 100}],
        2021: [{"cnpj": "A", "nome": "Alfa", "valor": 1000}, {"cnpj": "B", "nome": "Beta", "valor": 120}],
        2022: [{"cnpj": "A", "nome": "Alfa", "valor": 1000}, {"cnpj": "B", "nome": "Beta", "valor": 90}],
    }
    r = R._detectar_rodizio(por_ano)
    assert r["indicio"] is False and r["n_campeoes"] == 1


def test_exclui_entidade_intragov_do_topo():
    # O #1 bruto é repasse intra-gov; excluído, sobram 3 fornecedores reais se revezando
    por_ano = {
        2020: [{"cnpj": "G", "nome": "MINISTERIO DA FAZENDA", "valor": 9999},
               {"cnpj": "A", "nome": "Alfa", "valor": 1000}, {"cnpj": "B", "nome": "Beta", "valor": 200}],
        2021: [{"cnpj": "G", "nome": "MINISTERIO DA FAZENDA", "valor": 9999},
               {"cnpj": "B", "nome": "Beta", "valor": 1000}, {"cnpj": "A", "nome": "Alfa", "valor": 180}],
        2022: [{"cnpj": "G", "nome": "MINISTERIO DA FAZENDA", "valor": 9999},
               {"cnpj": "C", "nome": "Gama", "valor": 1000}, {"cnpj": "A", "nome": "Alfa", "valor": 160}],
    }
    r = R._detectar_rodizio(por_ano, eh_excluido=lambda nome: "FAZENDA" in (nome or ""))
    assert r["indicio"] is True and r["n_campeoes"] == 3
    assert "G" not in {c["cnpj"] for c in r["campeoes"]}


def test_topo_fino_que_se_reveza_sem_dominancia_nao_dispara():
    # 3 se revezam o #1, mas vários OUTROS fornecedores dominam o gasto → share_ring baixo → sem indício
    por_ano = {
        2020: [{"cnpj": "A", "nome": "Alfa", "valor": 500}, {"cnpj": "X1", "nome": "X1", "valor": 300},
               {"cnpj": "X2", "nome": "X2", "valor": 250}, {"cnpj": "X3", "nome": "X3", "valor": 200}],
        2021: [{"cnpj": "B", "nome": "Beta", "valor": 500}, {"cnpj": "X1", "nome": "X1", "valor": 300},
               {"cnpj": "X2", "nome": "X2", "valor": 250}, {"cnpj": "X3", "nome": "X3", "valor": 220}],
        2022: [{"cnpj": "C", "nome": "Gama", "valor": 500}, {"cnpj": "X1", "nome": "X1", "valor": 300},
               {"cnpj": "X2", "nome": "X2", "valor": 260}, {"cnpj": "X3", "nome": "X3", "valor": 210}],
    }
    r = R._detectar_rodizio(por_ano)
    assert r["indicio"] is False and r["share_ring"] < 0.6


def test_poucos_anos_nao_dispara():
    por_ano = {
        2020: [{"cnpj": "A", "nome": "Alfa", "valor": 1000}, {"cnpj": "B", "nome": "Beta", "valor": 800}],
        2021: [{"cnpj": "B", "nome": "Beta", "valor": 1000}, {"cnpj": "A", "nome": "Alfa", "valor": 800}],
    }
    r = R._detectar_rodizio(por_ano)  # só 2 anos < min_anos
    assert r["indicio"] is False
