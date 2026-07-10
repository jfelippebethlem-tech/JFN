# -*- coding: utf-8 -*-
"""Schema do enxame de editais no compliance.db (aditivo)."""
from __future__ import annotations

import sqlite3

from compliance_agent.emendas.db import conectar  # reexport: mesmo helper WAL/row_factory

__all__ = ["conectar", "init_schema", "DDL"]

DDL = [
    """CREATE TABLE IF NOT EXISTS edital_documento (
        numero_controle_pncp TEXT PRIMARY KEY, ano INTEGER, orgao_cnpj TEXT,
        objeto TEXT, material_servico TEXT, valor_estimado REAL,
        texto TEXT, itens_json TEXT, documento_disponivel INTEGER DEFAULT 0,
        coletado_em TEXT DEFAULT (datetime('now')))""",
    """CREATE TABLE IF NOT EXISTS edital_clausula (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero_controle_pncp TEXT NOT NULL REFERENCES edital_documento(numero_controle_pncp),
        eixo TEXT, subtipo TEXT, texto TEXT, parametro_num REAL,
        assinatura TEXT, trecho_fonte TEXT)""",
    "CREATE INDEX IF NOT EXISTS ix_clau_ctrl ON edital_clausula(numero_controle_pncp)",
    "CREATE INDEX IF NOT EXISTS ix_clau_assin ON edital_clausula(assinatura)",
    """CREATE TABLE IF NOT EXISTS edital_cluster (
        id INTEGER PRIMARY KEY AUTOINCREMENT, assinatura_objeto TEXT,
        membros_json TEXT, tamanho INTEGER, avaliavel INTEGER DEFAULT 0,
        criado_em TEXT DEFAULT (datetime('now')))""",
    """CREATE TABLE IF NOT EXISTS clausula_veredito (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        clausula_id INTEGER REFERENCES edital_clausula(id),
        cluster_id INTEGER REFERENCES edital_cluster(id),
        numero_controle_pncp TEXT, raridade REAL, forca_e7 TEXT, sumula TEXT,
        votos_json TEXT, score_final INTEGER, veredito TEXT,
        verificado_em TEXT DEFAULT (datetime('now')))""",
]


def init_schema(con: sqlite3.Connection) -> None:
    for ddl in DDL:
        con.execute(ddl)
    con.commit()
