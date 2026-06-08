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
