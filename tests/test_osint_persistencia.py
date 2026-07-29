# -*- coding: utf-8 -*-
"""Persistência do grafo de vínculos nas tabelas `pessoas` e `relacionamentos`.

Ambas existiam no schema com as colunas certas (`tipo`, `fonte`, `data_inicio`, `data_fim`) e
**zero linhas** — desenhadas e nunca preenchidas. O que este teste trava não é o INSERT, é a
honestidade do que se grava: `data_fim` NULA porque a fonte não observa saída de sócio, e aresta
sem procedência recusada na porta.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_osint_persistencia.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.osint.persistencia import (
    FTM_POR_TIPO,
    arestas_persistidas,
    para_ftm,
    salvar_grafo,
)
from compliance_agent.osint.vinculos import GrafoVinculos, no_pf, no_pj

_SCHEMA = """
CREATE TABLE pessoas (
  id INTEGER PRIMARY KEY, cpf VARCHAR(11), nome VARCHAR(200) NOT NULL, nome_mae VARCHAR(200),
  data_nasc DATE, tipo VARCHAR(30), cargo VARCHAR(200), orgao VARCHAR(200),
  matricula VARCHAR(50), ativo BOOLEAN, created_at DATETIME, updated_at DATETIME);
CREATE TABLE relacionamentos (
  id INTEGER PRIMARY KEY, pessoa_a_id INTEGER NOT NULL, pessoa_b_id INTEGER NOT NULL,
  tipo VARCHAR(50), descricao TEXT, fonte VARCHAR(100), data_inicio DATE, data_fim DATE,
  created_at DATETIME);
"""


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.executescript(_SCHEMA)
    yield c
    c.close()


def _grafo() -> GrafoVinculos:
    g = GrafoVinculos()
    alfa = no_pj("11111111000100")
    maria = no_pf("", "MARIA DA SILVA|123456")
    g.rotular(alfa, "ALFA LTDA"); g.rotular(maria, "MARIA DA SILVA")
    g.ligar(maria, alfa, "socio_de", fonte="QSA/RFB snapshot 2026-05", data="2019-08-16",
            detalhe="Sócio-Administrador")
    return g


def test_grava_e_nao_duplica(con):
    g = _grafo()
    r1 = salvar_grafo(con, g)
    assert r1["pessoas_novas"] == 2 and r1["arestas_novas"] == 1 and r1["recusadas"] == 0

    r2 = salvar_grafo(con, g)  # idempotência: gravar de novo não duplica
    assert r2["arestas_novas"] == 0 and r2["arestas_repetidas"] == 1
    assert con.execute("SELECT COUNT(*) FROM relacionamentos").fetchone()[0] == 1


def test_data_fim_nula_e_afirmacao_nao_esquecimento(con):
    """A Receita entrega entrada e nunca saída. Preencher `data_fim` com a data do snapshot
    inventaria um desligamento que ninguém observou."""
    salvar_grafo(con, _grafo())
    linha = con.execute("SELECT data_inicio, data_fim FROM relacionamentos").fetchone()
    assert linha[0] == "2019-08-16", "a data de ENTRADA, que a fonte traz, tem de ser gravada"
    assert linha[1] is None, "data_fim preenchida = desligamento inventado"


def test_cpf_mascarado_nao_vira_cpf(con):
    """Nó de PF sem documento entra com `cpf` NULO. Gravar seis dígitos num campo chamado `cpf`
    mente para o próximo leitor — e a colisão de máscara nesta base é de ~4%."""
    salvar_grafo(con, _grafo())
    r = con.execute("SELECT cpf, tipo FROM pessoas WHERE nome LIKE 'MARIA%'").fetchone()
    assert r[0] is None
    assert r[1] == "pessoa"
    e = con.execute("SELECT cpf, tipo FROM pessoas WHERE nome='ALFA LTDA'").fetchone()
    assert e[0] == "11111111000100" and e[1] == "empresa"


def test_aresta_sem_fonte_e_recusada(con):
    """Mesma regra do motor, repetida na porta da base: sem procedência, não entra."""
    g = _grafo()
    # burla o `ligar` (que já exige fonte) para simular o que outro caminho poderia inserir
    g.arestas[0].fonte = ""
    r = salvar_grafo(con, g)
    assert r["arestas_novas"] == 0 and r["recusadas"] == 1
    assert con.execute("SELECT COUNT(*) FROM relacionamentos").fetchone()[0] == 0


def test_leitura_de_volta(con):
    salvar_grafo(con, _grafo())
    linhas = arestas_persistidas(con, "MARIA")
    assert len(linhas) == 1
    assert linhas[0]["de"] == "MARIA DA SILVA" and linhas[0]["para"] == "ALFA LTDA"
    assert linhas[0]["tipo"] == "socio_de" and linhas[0]["fonte"].startswith("QSA/RFB")


def test_export_ftm_usa_ontologia_pronta(con):
    """Não inventamos ontologia: `Ownership`/`Family`/`Directorship` já significam algo fora de
    casa, e o painel já expõe `/api/grafo/ftm`."""
    salvar_grafo(con, _grafo())
    ftm = para_ftm(arestas_persistidas(con))
    assert ftm[0]["schema"] == "Ownership"
    assert ftm[0]["properties"]["startDate"] == ["2019-08-16"]
    assert ftm[0]["properties"]["endDate"] == [], "término não observado não pode virar data"
    assert FTM_POR_TIPO["parente_de"] == "Family"
