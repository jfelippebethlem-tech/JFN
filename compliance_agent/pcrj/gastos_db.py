# -*- coding: utf-8 -*-
"""Schema de gastos/contratos/licitações da PCRJ no compliance.db (aditivo).

POR QUE separado do pcrj/db.py: aquele cuida da base de FOLHA (pcrj_benef.db);
estas tabelas vivem no compliance.db junto das demais de fornecedores/sanções,
onde o cruzamento credor×QSA×sanção acontece por SQL puro.
"""
from __future__ import annotations

import sqlite3

DDL = [
    """CREATE TABLE IF NOT EXISTS pcrj_despesa (
        id INTEGER PRIMARY KEY AUTOINCREMENT, exercicio INTEGER NOT NULL,
        orgao TEXT, unidade TEXT, credor_documento TEXT, credor_nome TEXT,
        natureza TEXT, fonte_recurso TEXT,
        empenhado REAL, liquidado REAL, pago REAL,
        arquivo_origem TEXT, coletado_em TEXT DEFAULT (datetime('now')),
        UNIQUE(exercicio, orgao, credor_documento, natureza, fonte_recurso, arquivo_origem))""",
    "CREATE INDEX IF NOT EXISTS ix_pcrjdesp_credor ON pcrj_despesa(credor_documento)",
    """CREATE TABLE IF NOT EXISTS pcrj_contratos (
        numero_controle_pncp TEXT PRIMARY KEY, ano INTEGER,
        orgao_cnpj TEXT, orgao_nome TEXT, unidade TEXT,
        fornecedor_documento TEXT, fornecedor_nome TEXT, tipo TEXT, objeto TEXT,
        valor_inicial REAL, valor_global REAL, data_assinatura TEXT,
        vigencia_ini TEXT, vigencia_fim TEXT, num_aditivos INTEGER DEFAULT 0,
        fonte TEXT DEFAULT 'pncp', coletado_em TEXT DEFAULT (datetime('now')))""",
    "CREATE INDEX IF NOT EXISTS ix_pcrjcontr_forn ON pcrj_contratos(fornecedor_documento)",
    """CREATE TABLE IF NOT EXISTS pcrj_licitacoes (
        numero_controle_pncp TEXT PRIMARY KEY, ano INTEGER, modalidade TEXT,
        objeto TEXT, valor_estimado REAL, situacao TEXT, data_abertura TEXT,
        orgao_cnpj TEXT, orgao_nome TEXT, amparo TEXT,
        fonte TEXT DEFAULT 'pncp', coletado_em TEXT DEFAULT (datetime('now')))""",
]


def init_schema(con: sqlite3.Connection) -> None:
    for ddl in DDL:
        con.execute(ddl)
    # migração aditiva: link do contrato/empenho → COMPRA de origem no PNCP
    # (permite checar a modalidade de origem — ata × dispensa — no detector D7)
    cols = {r[1] for r in con.execute("PRAGMA table_info(pcrj_contratos)")}
    if "numero_compra" not in cols:
        con.execute("ALTER TABLE pcrj_contratos ADD COLUMN numero_compra TEXT")
    con.commit()
