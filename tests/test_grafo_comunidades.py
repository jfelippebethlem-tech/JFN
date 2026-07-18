# -*- coding: utf-8 -*-
"""grafo_comunidades — Louvain determinístico separa clãs e pontua risco por sinal objetivo."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.grafo_comunidades import construir_grafo_intel, detectar_comunidades


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE pncp_resultado (
        certame TEXT, orgao_cnpj TEXT, orgao_nome TEXT, uf TEXT, municipio TEXT,
        modalidade TEXT, objeto TEXT, data_pub TEXT, item INTEGER,
        fornecedor_cnpj TEXT, fornecedor_nome TEXT, valor_homologado REAL,
        ordem_classificacao INTEGER, porte_fornecedor TEXT);
    CREATE TABLE socios_receita (
        cnpj_basico TEXT, ident INTEGER, nome_socio TEXT, nome_norm TEXT, doc_socio TEXT,
        qualificacao_cod TEXT, qualificacao_txt TEXT, data_entrada TEXT,
        faixa_etaria TEXT, fonte_mes TEXT);
    CREATE TABLE sancoes_federais (cpf_cnpj TEXT, nome TEXT, cadastro TEXT, categoria TEXT,
        data_inicio TEXT, data_fim TEXT, orgao TEXT);
    """)
    ins = ("INSERT INTO pncp_resultado (certame, orgao_cnpj, orgao_nome, item, "
           "fornecedor_cnpj, fornecedor_nome, valor_homologado, ordem_classificacao) "
           "VALUES (?,?,?,?,?,?,?,?)")
    con.executemany(ins, [
        # clã 1: E1 e E2 (mesmo dono) vencem no órgão O1 e disputam "entre si"
        ("K1", "O1", "SES", 1, "11111111000111", "ALFA", 90000.0, 1),
        ("K1", "O1", "SES", 1, "22222222000122", "BETA", 0.0, 2),
        ("K2", "O1", "SES", 1, "22222222000122", "BETA", 70000.0, 1),
        ("K2", "O1", "SES", 1, "11111111000111", "ALFA", 0.0, 2),
        # clã 2: E3 vende p/ O2, sem relação com o clã 1
        ("K3", "O2", "SEFAZ", 1, "33333333000133", "GAMA", 40000.0, 1),
    ])
    con.executemany("INSERT INTO socios_receita (cnpj_basico, nome_socio, nome_norm, "
                    "doc_socio, qualificacao_txt) VALUES (?,?,?,?,?)", [
        ("11111111", "Joao Xavier", "JOAO XAVIER", "***123456**", "Sócio-Administrador"),
        ("22222222", "Joao Xavier", "JOAO XAVIER", "***123456**", "Sócio"),
        ("33333333", "Maria Lima", "MARIA LIMA", "***777777**", "Sócio"),
    ])
    con.execute("INSERT INTO sancoes_federais VALUES "
                "('11111111000111','ALFA','CEIS','Impedimento','2023-01-01','2026-12-31','CGU')")
    con.commit()
    con.close()
    return p


def test_grafo_tem_3_tipos_de_no(db):
    G = construir_grafo_intel(db)
    tipos = {G.nodes[n]["tipo"] for n in G.nodes}
    assert tipos == {"pessoa", "empresa", "orgao"}
    assert G.get_edge_data("emp:11111111", "emp:22222222")["tipo"] == "coparticipacao"


def test_louvain_separa_os_clas_e_pontua_risco(db):
    d = detectar_comunidades(db_path=db, min_tamanho=3, incluir_grafo_d3=False)
    assert d["ok"] is True and d["n"] >= 1
    c0 = d["comunidades"][0]
    ids = {m["id"] for m in c0["membros"]}
    # o clã do dono comum fica junto: pessoa + as duas empresas
    assert {"emp:11111111", "emp:22222222"} <= ids
    assert "emp:33333333" not in ids
    # sinais: conluio direto (A×B com sócio comum) + sancionada + órgão dominante
    sinais = {s["sinal"] for s in c0["sinais"]}
    assert "conluio_direto" in sinais and "sancionada" in sinais
    assert c0["score"] >= 50 and c0["rating"] == "🔴"


def test_deterministico_mesma_seed(db):
    d1 = detectar_comunidades(db_path=db, min_tamanho=3, incluir_grafo_d3=False)
    d2 = detectar_comunidades(db_path=db, min_tamanho=3, incluir_grafo_d3=False)
    assert [c["score"] for c in d1["comunidades"]] == [c["score"] for c in d2["comunidades"]]
    assert [sorted(m["id"] for m in c["membros"]) for c in d1["comunidades"]] == \
           [sorted(m["id"] for m in c["membros"]) for c in d2["comunidades"]]


def test_escala_e_ressalva_presentes(db):
    d = detectar_comunidades(db_path=db, min_tamanho=3, incluir_grafo_d3=False)
    assert "0-100" in d["escala"] and "Indício" in d["ressalva"]
