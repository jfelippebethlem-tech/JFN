# -*- coding: utf-8 -*-
"""economia_vedada — sobrepreço pago a fornecedor JURIDICAMENTE VEDADO (à época + veda o ente)."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import comparador_precos as CP


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE pncp_resultado (item_descricao TEXT, unidade_medida TEXT, valor_unitario REAL,
        quantidade REAL, orgao_cnpj TEXT, orgao_nome TEXT, unidade_nome TEXT, uf TEXT,
        fornecedor_nome TEXT, fornecedor_cnpj TEXT, ordem_classificacao INTEGER, data_pub TEXT,
        certame TEXT);
    CREATE TABLE sancoes_federais (cpf_cnpj TEXT, nome TEXT, cadastro TEXT, categoria TEXT,
        data_inicio TEXT, data_fim TEXT, orgao TEXT, uf TEXT, fundamentacao TEXT);
    CREATE TABLE pncp_ente (cnpj TEXT, nome TEXT, esfera_id TEXT, poder_id TEXT,
        natureza_juridica TEXT, coletado_em TEXT);
    """)
    ins = ("INSERT INTO pncp_resultado (item_descricao, unidade_medida, valor_unitario, quantidade, "
           "orgao_cnpj, orgao_nome, unidade_nome, uf, fornecedor_nome, fornecedor_cnpj, "
           "ordem_classificacao, data_pub, certame) VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)")
    INID = "99999999000199"   # inidônea (veda todos)
    LIMP = "11111111000111"
    ORG = "00000000000100"    # órgão comprador (estadual)
    # Cadeira: mediana ~10 (5 compras). A inidônea paga 30 (excesso 20) × 10 unid, DENTRO da vigência
    rows = [
        ("Cadeira", "UN", 10.0, 10, ORG, "SES", "SES", "RJ", "L", LIMP, "2025-06-01", "c1"),
        ("Cadeira", "UN", 10.0, 10, ORG, "SES", "SES", "RJ", "L", LIMP, "2025-06-02", "c2"),
        ("Cadeira", "UN", 11.0, 10, ORG, "SES", "SES", "RJ", "L", LIMP, "2025-06-03", "c3"),
        ("Cadeira", "UN", 9.0, 10, ORG, "SES", "SES", "RJ", "L", LIMP, "2025-06-04", "c4"),
        ("Cadeira", "UN", 30.0, 10, ORG, "SES", "SES", "RJ", "INIDONEA", INID, "2025-06-10", "c5"),
    ]
    con.executemany(ins, rows)
    con.execute("INSERT INTO pncp_ente VALUES (?,?,?,?,?,?)", (ORG, "SES", "E", "E", "", ""))
    con.execute("INSERT INTO sancoes_federais VALUES (?,?,?,?,?,?,?,?,?)",
                (INID, "INIDONEA", "CEIS", "Declaração de Inidoneidade com prazo determinado",
                 "2025-01-01", "2027-01-01", "TCU", "DF", ""))
    con.commit()
    con.close()
    return p


def test_soma_sobrepreco_a_inidoneo_vigente(db):
    d = CP.economia_vedada(db_path=db, min_amostra=5, min_orgaos=1, min_certames=3)
    assert d["ok"] is True
    # mediana [9,10,10,11,30]=10 → excesso (30-10)×10 = 200
    assert d["economia_vedada_total"] == pytest.approx(200.0)
    assert d["por_abrangencia"]["total"] == pytest.approx(200.0)
    assert d["por_fornecedor"][0]["fornecedor_cnpj"] == "99999999000199"
    assert d["por_fornecedor"][0]["abrangencia"] == "total"


def test_sancao_fora_da_vigencia_nao_conta(db):
    con = sqlite3.connect(db)
    con.execute("UPDATE sancoes_federais SET data_inicio='2026-01-01', data_fim='2027-01-01'")
    con.commit()
    con.close()
    # compra em 2025-06-10, sanção só a partir de 2026 → NÃO estava vedado à época
    d = CP.economia_vedada(db_path=db, min_amostra=5, min_orgaos=1, min_certames=3)
    assert d["economia_vedada_total"] == 0.0


def test_impedimento_federal_nao_veda_comprador_estadual(db):
    con = sqlite3.connect(db)
    con.execute("UPDATE sancoes_federais SET categoria='Impedimento/proibição de contratar com "
                "prazo determinado', orgao='Tribunal Regional Federal da 2ª Região', uf='RJ'")
    con.commit()
    con.close()
    # impedimento FEDERAL não veda contrato com órgão ESTADUAL (esfera E) → não conta
    d = CP.economia_vedada(db_path=db, min_amostra=5, min_orgaos=1, min_certames=3)
    assert d["economia_vedada_total"] == 0.0


def test_ressalva_presente(db):
    d = CP.economia_vedada(db_path=db, min_amostra=5, min_orgaos=1)
    assert "Indício" in d["ressalva"] and "independentes" in d["ressalva"].lower()
