# -*- coding: utf-8 -*-
"""Task 4.1 — coletor de propostas de concorrentes → tabela `proposta_item` (plano-mestre F4)."""
import json
import sqlite3

import pytest

from compliance_agent.editais.coletor_propostas import (
    ITEM_LANCE_GLOBAL,
    coletar_certame,
    garantir_tabela,
    persistir_propostas,
)

CERTAME = "PNCP-TESTE-001/2026"

# 3 licitantes com lance TOTAL literal (CNPJ formatado + R$) — formato que _extrair_propostas entende.
ATA_TEXTO = """ATA DA SESSÃO PÚBLICA DE JULGAMENTO DAS PROPOSTAS

A empresa ALFA COMERCIO LTDA, inscrita no CNPJ 12.345.678/0001-95, apresentou proposta no valor de R$ 99.500,00 e foi declarada vencedora do certame.

A empresa BETA SERVICOS LTDA, inscrita no CNPJ 98.765.432/0001-10, apresentou proposta no valor de R$ 100.000,00, classificada em segundo lugar.

A empresa GAMA SUPRIMENTOS LTDA, inscrita no CNPJ 11.222.333/0001-81, apresentou proposta no valor de R$ 100.100,00.
"""


def _propostas_3x2() -> list[dict]:
    """3 fornecedores × 2 itens unitários (dicts canônicos do persistir_propostas)."""
    out = []
    for f, cnpj in [("ALFA", "12345678000195"), ("BETA", "98765432000110"), ("GAMA", "11222333000181")]:
        for item, vu in [(1, 10.5), (2, 20.0)]:
            out.append({"item": item, "fornecedor_cnpj": cnpj, "fornecedor_nome": f,
                        "valor_unitario": vu, "valor_total": vu, "fonte": "sei_precos",
                        "trecho": f"{item} | material {item} | {vu}"})
    return out


@pytest.fixture()
def con():
    con = sqlite3.connect(":memory:")
    garantir_tabela(con)
    yield con
    con.close()


@pytest.fixture()
def db_com_ata(tmp_path):
    """compliance.db mínimo com a tabela `ata_documento` de produção + 1 ata do certame."""
    db = tmp_path / "compliance.db"
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE ata_documento (
        certame TEXT NOT NULL, orgao_cnpj TEXT, titulo TEXT, fonte_texto TEXT,
        n_cnpj INTEGER, texto TEXT, coletado_em TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (certame, titulo))""")
    con.execute("INSERT INTO ata_documento (certame, orgao_cnpj, titulo, fonte_texto, n_cnpj, texto) "
                "VALUES (?,?,?,?,?,?)", (CERTAME, "00000000000191", "Ata de Julgamento", "pdf", 3, ATA_TEXTO))
    con.commit()
    con.close()
    return db


def test_garantir_tabela_idempotente(con):
    garantir_tabela(con)  # 2ª chamada não explode (IF NOT EXISTS)
    cols = [r[1] for r in con.execute("PRAGMA table_info(proposta_item)")]
    assert cols == ["certame", "item", "fornecedor_cnpj", "fornecedor_nome", "valor_unitario",
                    "valor_total", "classificacao", "marca", "fonte", "sha_evidencia"]


def test_persistir_3_licitantes_2_itens_6_linhas(con):
    propostas = _propostas_3x2()
    # linha SEM valor numérico literal NÃO entra (ausente ≠ 0)
    propostas.append({"item": 3, "fornecedor_cnpj": "12345678000195", "fonte": "sei_precos"})
    assert persistir_propostas(con, CERTAME, propostas) == 6
    assert con.execute("SELECT COUNT(*) FROM proposta_item").fetchone()[0] == 6


def test_persistir_idempotente(con):
    persistir_propostas(con, CERTAME, _propostas_3x2())
    persistir_propostas(con, CERTAME, _propostas_3x2())  # INSERT OR REPLACE: sem duplicar
    assert con.execute("SELECT COUNT(*) FROM proposta_item").fetchone()[0] == 6


def test_persistir_guards_honestos(con):
    n = persistir_propostas(con, CERTAME, [
        {"item": 1, "fornecedor_cnpj": "123", "valor_unitario": 10.0, "fonte": "ata"},          # CNPJ != 14
        {"item": 1, "fornecedor_cnpj": "12345678000195", "valor_unitario": 10.0, "fonte": "x"},  # fonte inválida
        {"item": 1, "fornecedor_cnpj": "12345678000195", "valor_unitario": "10,00", "fonte": "ata"},  # valor não numérico
    ])
    assert n == 0
    # classificacao: só INTEIRO literal vira rank; rótulo textual fica NULL
    persistir_propostas(con, CERTAME, [
        {"item": 1, "fornecedor_cnpj": "12345678000195", "valor_total": 9.0,
         "classificacao": "classificada", "fonte": "ata"},
        {"item": 1, "fornecedor_cnpj": "98765432000110", "valor_total": 9.5,
         "classificacao": 2, "fonte": "ata", "trecho": "proposta de R$ 9,50"},
    ])
    rows = dict(con.execute("SELECT fornecedor_cnpj, classificacao FROM proposta_item").fetchall())
    assert rows["12345678000195"] is None
    assert rows["98765432000110"] == 2
    sha = con.execute("SELECT sha_evidencia FROM proposta_item WHERE fornecedor_cnpj='98765432000110'").fetchone()[0]
    assert sha and len(sha) == 16


def test_coletar_certame_persiste_lances_da_ata(db_com_ata):
    assert coletar_certame(CERTAME, db_com_ata) == 3
    con = sqlite3.connect(db_com_ata)
    rows = con.execute("SELECT item, fornecedor_cnpj, valor_total, fonte, sha_evidencia "
                       "FROM proposta_item ORDER BY valor_total").fetchall()
    con.close()
    assert [r[2] for r in rows] == [99500.0, 100000.0, 100100.0]
    assert all(r[0] == ITEM_LANCE_GLOBAL and r[3] == "ata" and r[4] for r in rows)
    assert {r[1] for r in rows} == {"12345678000195", "98765432000110", "11222333000181"}


def test_coletar_certame_sem_ata_retorna_zero(tmp_path):
    db = tmp_path / "vazio.db"
    sqlite3.connect(db).close()  # DB sem ata_documento — sem fonte, sem invenção
    assert coletar_certame("CERTAME-INEXISTENTE", db) == 0


def test_coletar_certame_itens_unitarios_via_gerar(db_com_ata):
    """Com motor LLM (`gerar`) o extrator_precos devolve itens unitários → fonte='sei_precos'."""
    itens = [
        {"item": "1", "descricao": "Caneta esferografica azul", "valor_unitario": "10,50",
         "cnpj": "12345678000195", "fornecedor": "ALFA"},
        {"item": "2", "descricao": "Caderno pautado 96 folhas", "valor_unitario": "20,00",
         "cnpj": "12345678000195", "fornecedor": "ALFA"},
    ]
    n = coletar_certame(CERTAME, db_com_ata, gerar=lambda _prompt: json.dumps(itens))
    assert n == 5  # 3 lances da ata + 2 itens unitários
    con = sqlite3.connect(db_com_ata)
    rows = con.execute("SELECT item, valor_unitario FROM proposta_item WHERE fonte='sei_precos' "
                       "ORDER BY item").fetchall()
    con.close()
    assert rows == [(1, 10.5), (2, 20.0)]
