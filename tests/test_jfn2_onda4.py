# -*- coding: utf-8 -*-
"""Testes da Onda 4 (Grafo de Poder): vizinhança por expansão local, sobre DB sintético."""
from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def grafo_db(tmp_path, monkeypatch):
    """DB mínimo: empresa A (sócio FULANO, paga pela UG 111111); FULANO doou ao CAND X."""
    db = tmp_path / "g.db"
    con = sqlite3.connect(str(db))
    con.executescript(
        """
        CREATE TABLE socios_fornecedor (cnpj TEXT, razao TEXT, socio_nome TEXT,
            socio_nome_norm TEXT, socio_doc TEXT, qualificacao TEXT, ingerido_em TEXT);
        CREATE TABLE ordens_bancarias (favorecido_cpf TEXT, favorecido_nome TEXT,
            ug_codigo TEXT, ug_nome TEXT, valor REAL);
        CREATE TABLE doacoes_eleitorais (cpf_cnpj_doador TEXT, nome_doador TEXT,
            nome_candidato TEXT, partido TEXT, valor REAL);
        CREATE TABLE endereco_fornecedor (cnpj TEXT, endereco_norm TEXT);
        CREATE TABLE registros_folha (nome TEXT, ug_codigo TEXT);
        """
    )
    con.execute("INSERT INTO socios_fornecedor VALUES (?,?,?,?,?,?,?)",
                ("11111111000111", "EMPRESA A", "FULANO DE TAL", "FULANO DE TAL", "***123456**", "Sócio", ""))
    con.execute("INSERT INTO ordens_bancarias VALUES (?,?,?,?,?)",
                ("11.111.111/0001-11", "EMPRESA A", "111111", "UG TESTE", 500000.0))
    con.execute("INSERT INTO doacoes_eleitorais VALUES (?,?,?,?,?)",
                ("***123456**", "FULANO DE TAL", "CANDIDATO X", "PT", 10000.0))
    con.commit()
    con.close()

    from compliance_agent import grafo_poder
    monkeypatch.setattr(grafo_poder, "_DB", db)
    return grafo_poder


def test_vizinhanca_une_socio_ob_doacao(grafo_db):
    """A partir do CNPJ chega-se à UG (pago_por), ao sócio (socio) e ao candidato (doou)."""
    r = grafo_db.vizinhanca("11111111000111", saltos=2)
    assert r["ok"] is True and r["raiz"] == "cnpj:11111111000111"
    tipos = {n["tipo"] for n in r["nos"]}
    assert {"cnpj", "ug", "socio", "cand"} <= tipos
    rels = {a["rel"] for a in r["arestas"]}
    assert {"pago_por", "socio", "doou"} <= rels


def test_so_contrato_foca_dinheiro(grafo_db):
    """so_contrato=true não traz a aresta de doação (foca cnpj↔ug↔sócio)."""
    r = grafo_db.vizinhanca("11111111000111", saltos=2, so_contrato=True)
    rels = {a["rel"] for a in r["arestas"]}
    assert "doou" not in rels
    assert "pago_por" in rels


def test_alvo_inexistente_honesto(grafo_db):
    """Alvo não encontrado => nós vazios + nota INDISPONÍVEL (não inventa)."""
    r = grafo_db.vizinhanca("99999999999999")
    assert r["nos"] == [] and "INDISPONÍVEL" in r["_nota"]


def test_capability_grafo_pronto():
    from compliance_agent.skilltree import SkillTree

    st = SkillTree()
    st.reload()
    cap = st.capacidades.get("grafo_poder")
    assert cap is not None and cap["status"] == "PRONTO" and cap["rota"] == "/api/grafo"
    assert st.validate() == []


# ---- Onda 4b: Dossiê 360 (agregação honesta; mock das fontes de rede) ----

def test_dossie_agrega_e_score(monkeypatch, tmp_path):
    """dossie() une cadastro+sanções+OB+conflito+rede e calcula o score dos sinais."""
    import asyncio

    from compliance_agent import dossie as D

    async def fake_cnpj(cnpj, client=None):
        return {"razao_social": "EMPRESA TESTE LTDA", "cnpj": cnpj}

    async def fake_sancao(cnpj, forcar_update=False):
        return {"sancionado": True, "sancoes": [{"tipo": "CEIS"}]}

    monkeypatch.setattr("compliance_agent.collectors.cnpj.buscar_cnpj", fake_cnpj)
    monkeypatch.setattr("compliance_agent.collectors.ceis.verificar_sancao", fake_sancao)
    monkeypatch.setattr("compliance_agent.lex_conflito.conflito",
                        lambda cnpj=None, candidato=None, limite=200: {"rede": [{"x": 1}], "_nota": "n"})
    monkeypatch.setattr("compliance_agent.grafo_poder.vizinhanca",
                        lambda alvo, saltos=2, so_contrato=False: {"n_nos": 5, "arestas": [], "nos": []})
    # DB vazio p/ _resumo_ob (sem OB) — não fabrica
    db = tmp_path / "x.db"
    import sqlite3
    sqlite3.connect(str(db)).executescript(
        "CREATE TABLE ordens_bancarias (favorecido_cpf TEXT, ug_codigo TEXT, ug_nome TEXT, valor REAL);")
    monkeypatch.setattr(D, "_DB", db)

    d = asyncio.run(D.dossie("11111111000111", gerar_pdf=False))
    assert d["ok"] is True
    assert d["cadastro"]["razao_social"] == "EMPRESA TESTE LTDA"
    # score = conflito (25) + sanção (20); concentração 0 (sem OB)
    flags = {c["flag"] for c in d["score"]["contribuicoes"]}
    assert "conflito_doador" in flags and "sancao_ceis_cnep" in flags
    assert d["score"]["score"] >= 40


def test_dossie_fonte_indisponivel_nao_fabrica(monkeypatch, tmp_path):
    """Se uma fonte falha, vira INDISPONÍVEL — nunca inventa."""
    import asyncio

    from compliance_agent import dossie as D

    async def boom(*a, **k):
        raise RuntimeError("rede caiu")

    monkeypatch.setattr("compliance_agent.collectors.cnpj.buscar_cnpj", boom)
    monkeypatch.setattr("compliance_agent.collectors.ceis.verificar_sancao", boom)
    db = tmp_path / "y.db"
    import sqlite3
    sqlite3.connect(str(db)).executescript(
        "CREATE TABLE ordens_bancarias (favorecido_cpf TEXT, ug_codigo TEXT, ug_nome TEXT, valor REAL);")
    monkeypatch.setattr(D, "_DB", db)
    monkeypatch.setattr("compliance_agent.lex_conflito.conflito",
                        lambda **k: {"rede": []})
    monkeypatch.setattr("compliance_agent.grafo_poder.vizinhanca",
                        lambda *a, **k: {"n_nos": 0, "arestas": [], "nos": []})

    d = asyncio.run(D.dossie("11111111000111", gerar_pdf=False))
    assert "INDISPONÍVEL" in d["cadastro"]["_nota"]
    assert d["ok"] is True  # o dossiê não quebra por uma fonte fora


def test_capability_dossie_pronto():
    from compliance_agent.skilltree import SkillTree

    st = SkillTree()
    st.reload()
    cap = st.capacidades.get("dossie")
    assert cap is not None and cap["status"] == "PRONTO" and cap["rota"] == "/api/dossie"
    assert st.validate() == []
