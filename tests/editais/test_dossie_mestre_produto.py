# -*- coding: utf-8 -*-
"""Produto Dossiê Mestre (F5.5) — ctx Kroll de órgão e portfólio (puro, sem PDF).
Rodar só este arquivo:  .venv/bin/python -m pytest tests/editais/test_dossie_mestre_produto.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.editais.db import init_schema
from compliance_agent.reporting.dossie_mestre import montar_ctx_orgao, montar_ctx_portfolio

PNCP_DDL = """CREATE TABLE pncp_resultado (certame TEXT, orgao_cnpj TEXT, orgao_nome TEXT,
    uf TEXT, municipio TEXT, modalidade INTEGER, objeto TEXT, data_pub TEXT, item INTEGER,
    fornecedor_cnpj TEXT, fornecedor_nome TEXT, valor_homologado REAL, ordem_classificacao INTEGER,
    porte_fornecedor TEXT, coletado_em TEXT, unidade_codigo TEXT, unidade_nome TEXT,
    item_descricao TEXT, unidade_medida TEXT, valor_unitario REAL, quantidade REAL)"""
ORG = "30051023000196"


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    init_schema(con)
    con.execute(PNCP_DDL)
    for i in range(4):
        c = f"{ORG}-1-00000{i}/2026"
        con.execute("INSERT INTO edital_documento (numero_controle_pncp, ano, orgao_cnpj) "
                    "VALUES (?, 2026, ?)", (c, ORG))
        con.execute("INSERT INTO certame_indice (certame, score, prioridade, faixa, confianca) "
                    "VALUES (?, ?, 1, ?, 0.5)", (c, 40.0 + 10 * i, "MEDIO" if i < 3 else "ALTO"))
        con.execute("INSERT INTO pncp_resultado (certame, orgao_cnpj, orgao_nome, uf, fornecedor_cnpj, "
                    "ordem_classificacao) VALUES (?, ?, ?, 'RJ', '11111111000191', 1)",
                    (c, ORG, "TRIBUNAL DE CONTAS DO ESTADO DO RIO DE JANEIRO"))  # esfera estadual-rj
    con.commit()
    yield p, con
    con.close()


def test_ctx_orgao_tem_capa_metodologia_e_conjunto(db):
    p, _con = db
    ctx = montar_ctx_orgao(ORG, db_path=p)
    assert ctx["titulo"].startswith("Dossiê Mestre")
    assert ORG in ctx["subtitulo"]
    titulos = [s["titulo"] for s in ctx["secoes"]]
    assert "Metodologia" in titulos
    assert any("conjunto" in t.lower() for t in titulos)
    assert ctx["score"] == 55  # mediana de 40/50/60/70


def test_ctx_portfolio_ranqueia(db):
    p, _con = db
    ctx = montar_ctx_portfolio(db_path=p, min_certames=3)
    assert "Portfólio" in ctx["titulo"]
    ranking = next(s for s in ctx["secoes"] if s["titulo"].startswith("Ranking de órgãos"))
    assert "TRIBUNAL DE CONTAS" in ranking["html"]
    assert any(s["titulo"] == "Ranking por unidade/secretaria" for s in ctx["secoes"])


def test_ctx_renderiza_sem_erro(db):
    # o ctx tem de passar pelo render Kroll (chaves esperadas presentes)
    from compliance_agent.reporting.render_html import render_html
    p, _con = db
    html = render_html(montar_ctx_orgao(ORG, db_path=p))
    assert "Dossiê Mestre" in html and "Metodologia" in html
