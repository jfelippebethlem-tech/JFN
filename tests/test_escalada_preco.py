# -*- coding: utf-8 -*-
"""escalada_preco — mesmo fornecedor sobe o preço do mesmo item ao longo do tempo (preço dirigido)."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.cruzamentos_intel import escalada_preco


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE pncp_resultado (certame TEXT, orgao_nome TEXT, unidade_nome TEXT,
        municipio TEXT, item_descricao TEXT, unidade_medida TEXT, valor_unitario REAL,
        quantidade REAL, fornecedor_cnpj TEXT, fornecedor_nome TEXT, ordem_classificacao INTEGER,
        data_pub TEXT)""")
    ins = ("INSERT INTO pncp_resultado (certame, orgao_nome, unidade_nome, item_descricao, "
           "unidade_medida, valor_unitario, quantidade, fornecedor_cnpj, fornecedor_nome, "
           "ordem_classificacao, data_pub) VALUES (?,?,?,?,?,?,?,?,?,1,?)")
    A = "11111111000111"
    rows = [
        # ALFA escala "lampada led" (UN): 2 → 4 → 10 em 90 dias → 5x, acima do mercado
        ("C1", "SES", "SES", "Lampada LED", "UN", 2.0, 100, A, "ALFA", "2025-01-10"),
        ("C2", "SES", "SES", "Lampada LED", "UN", 4.0, 100, A, "ALFA", "2025-02-20"),
        ("C3", "SES", "SES", "Lampada LED", "UN", 10.0, 100, A, "ALFA", "2025-04-15"),
        # mercado (outros fornecedores) da lampada ~ 2.0
        ("M1", "X", "X", "Lampada LED", "UN", 2.0, 50, "22222222000122", "BETA", "2025-01-01"),
        ("M2", "Y", "Y", "Lampada LED", "UN", 2.2, 50, "33333333000133", "GAMA", "2025-01-01"),
        ("M3", "Z", "Z", "Lampada LED", "UN", 1.8, 50, "44444444000144", "DELTA", "2025-01-01"),
        ("M4", "W", "W", "Lampada LED", "UN", 2.1, 50, "55555555000155", "EPS", "2025-01-01"),
        ("M5", "V", "V", "Lampada LED", "UN", 2.0, 50, "66666666000166", "ZETA", "2025-01-01"),
    ]
    con.executemany(ins, rows)
    con.commit()
    con.close()
    return p


def test_detecta_escalada_com_serie_e_mercado(db):
    d = escalada_preco(db_path=db, min_compras=3, fator=3.0, min_span_dias=45)
    assert d["ok"] is True and d["n"] == 1
    a = d["achados"][0]
    assert a["fornecedor_cnpj"] == "11111111000111"
    assert a["preco_inicial"] == 2.0 and a["preco_final"] == 10.0 and a["razao"] == 5.0
    assert a["span_dias"] >= 45 and a["n_compras"] == 3
    # mediana de mercado inclui o próprio fornecedor (conservador): 10 / 2.05 ≈ 4.9
    assert a["final_vs_mercado"] == pytest.approx(4.9, abs=0.1)
    assert [s["preco"] for s in a["serie"]] == [2.0, 4.0, 10.0]


def test_span_curto_nao_conta(db):
    # exigindo 120 dias de janela, a série de 95 dias não passa
    d = escalada_preco(db_path=db, min_compras=3, fator=3.0, min_span_dias=120)
    assert d["n"] == 0


def test_fator_alto_nao_conta(db):
    d = escalada_preco(db_path=db, min_compras=3, fator=10.0, min_span_dias=45)
    assert d["n"] == 0                          # subiu só 5×, não 10×


def test_inicio_artefato_e_descartado(tmp_path):
    p = str(tmp_path / "a.db")
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE pncp_resultado (certame TEXT, orgao_nome TEXT, unidade_nome TEXT,
        municipio TEXT, item_descricao TEXT, unidade_medida TEXT, valor_unitario REAL,
        quantidade REAL, fornecedor_cnpj TEXT, fornecedor_nome TEXT, ordem_classificacao INTEGER,
        data_pub TEXT)""")
    ins = ("INSERT INTO pncp_resultado (certame, orgao_nome, unidade_nome, item_descricao, "
           "unidade_medida, valor_unitario, quantidade, fornecedor_cnpj, fornecedor_nome, "
           "ordem_classificacao, data_pub) VALUES (?,?,?,?,?,?,?,?,?,1,?)")
    A = "11111111000111"
    rows = [
        # início R$0,10 é artefato (< 10% da mediana de mercado ~100) → série descartada
        ("C1", "S", "S", "Dieta", "UN", 0.10, 10, A, "ALFA", "2025-01-10"),
        ("C2", "S", "S", "Dieta", "UN", 60.0, 10, A, "ALFA", "2025-03-10"),
        ("C3", "S", "S", "Dieta", "UN", 125.0, 10, A, "ALFA", "2025-05-10"),
    ] + [(f"M{i}", "X", "X", "Dieta", "UN", 100.0, 5, f"{i:014d}", "MKT", "2025-01-01")
         for i in range(1, 7)]
    con.executemany(ins, rows)
    con.commit()
    con.close()
    d = escalada_preco(db_path=p, min_compras=3, fator=3.0, min_span_dias=45)
    assert d["n"] == 0                          # o R$0,10 inicial (artefato) não vira base de razão


def test_ressalva_presente(db):
    d = escalada_preco(db_path=db)
    assert "Indício" in d["ressalva"] and "reajuste" in d["ressalva"].lower()


def _db_series(tmp_path, rows):
    p = str(tmp_path / "s.db")
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE pncp_resultado (certame TEXT, orgao_nome TEXT, unidade_nome TEXT,
        municipio TEXT, item_descricao TEXT, unidade_medida TEXT, valor_unitario REAL,
        quantidade REAL, fornecedor_cnpj TEXT, fornecedor_nome TEXT, ordem_classificacao INTEGER,
        data_pub TEXT)""")
    con.executemany("INSERT INTO pncp_resultado (certame, orgao_nome, unidade_nome, item_descricao, "
                    "unidade_medida, valor_unitario, quantidade, fornecedor_cnpj, fornecedor_nome, "
                    "ordem_classificacao, data_pub) VALUES (?,?,?,?,?,?,?,?,?,1,?)", rows)
    con.commit()
    con.close()
    return p


def test_apresentacao_diferente_nao_e_escalada(tmp_path):
    # galão de 5 L a R$ 5 e galão de 20 L a R$ 20: o agrupamento antigo ('galaol' = 'galaol') via 4×;
    # na unidade normalizada são apresentações diferentes — nenhuma série de 3
    A = "11111111000111"
    p = _db_series(tmp_path, [
        ("C1", "S", "S", "Agua mineral", "Galão 5 L", 5.0, 10, A, "ALFA", "2025-01-10"),
        ("C2", "S", "S", "Agua mineral", "Galão 5 L", 5.5, 10, A, "ALFA", "2025-02-10"),
        ("C3", "S", "S", "Agua mineral", "Galão 20 L", 20.0, 10, A, "ALFA", "2025-04-10"),
    ])
    d = escalada_preco(db_path=p, min_compras=3, fator=3.0, min_span_dias=45)
    assert d["n"] == 0


def test_unidade_ambigua_sai_da_serie_e_e_contada(tmp_path):
    # a 3ª compra em 'Caixa' (sem conteúdo) não pode virar o "preço final" da escalada
    A = "11111111000111"
    p = _db_series(tmp_path, [
        ("C1", "S", "S", "Lampada LED", "UN", 2.0, 100, A, "ALFA", "2025-01-10"),
        ("C2", "S", "S", "Lampada LED", "UN", 2.2, 100, A, "ALFA", "2025-02-20"),
        ("C3", "S", "S", "Lampada LED", "Caixa", 40.0, 5, A, "ALFA", "2025-04-15"),
    ])
    d = escalada_preco(db_path=p, min_compras=3, fator=3.0, min_span_dias=45)
    assert d["n"] == 0
    assert d["indeterminados"]["n"] == 1


def test_caixa_com_contagem_vira_preco_por_unidade(tmp_path):
    # 'Caixa 10 UN' a R$ 100 = R$ 10/un: a série por unidade é 2 → 4 → 10 (5×)
    A = "11111111000111"
    p = _db_series(tmp_path, [
        ("C1", "S", "S", "Lampada LED", "UN", 2.0, 100, A, "ALFA", "2025-01-10"),
        ("C2", "S", "S", "Lampada LED", "UN", 4.0, 100, A, "ALFA", "2025-02-20"),
        ("C3", "S", "S", "Lampada LED", "Caixa 10 UN", 100.0, 10, A, "ALFA", "2025-04-15"),
    ])
    d = escalada_preco(db_path=p, min_compras=3, fator=3.0, min_span_dias=45)
    assert d["n"] == 1
    a = d["achados"][0]
    assert a["preco_final"] == 10.0 and a["razao"] == 5.0 and a["unidade_normalizada"] == "unidade"


def test_salto_entre_compras_consecutivas_e_indeterminado(tmp_path):
    # medido no banco real (14/11/2026): 'Dieta enteral' por litro de R$ 58,98 a R$ 64.590,00
    # (1.095×) ia ao TOPO da escalada. Salto ≥ GAP× entre preços consecutivos é unidade ou
    # produto diferente (doutrina do preco_normalizado) — sai da conta, contado e com motivo.
    A = "11111111000111"
    p = _db_series(tmp_path, [
        ("C1", "S", "S", "Dieta enteral", "Litro", 58.98, 10, A, "ALFA", "2025-01-10"),
        ("C2", "S", "S", "Dieta enteral", "Litro", 60.0, 10, A, "ALFA", "2025-02-10"),
        ("C3", "S", "S", "Dieta enteral", "Litro", 64590.0, 10, A, "ALFA", "2025-04-10"),
    ])
    d = escalada_preco(db_path=p, min_compras=3, fator=3.0, min_span_dias=45)
    assert d["n"] == 0
    assert d["indeterminados"]["n"] == 3
    assert any("salto" in m["motivo"] for m in d["indeterminados"]["por_motivo"])
