# -*- coding: utf-8 -*-
"""Schema do enxame de contratos no compliance.db (aditivo)."""
from __future__ import annotations

import sqlite3

from compliance_agent.emendas.db import conectar

__all__ = ["conectar", "init_schema", "DDL"]

DDL = [
    """CREATE TABLE IF NOT EXISTS contrato_aditivo (
        id INTEGER PRIMARY KEY AUTOINCREMENT, numero_controle_pncp TEXT NOT NULL,
        sequencial_termo INTEGER, numero_termo TEXT, objeto TEXT,
        valor_acrescido REAL, valor_global REAL, prazo_aditado_dias INTEGER,
        vigencia_fim TEXT, qualif_acrescimo TEXT, qualif_vigencia TEXT, qualif_reajuste TEXT,
        fundamento_legal TEXT, coletado_em TEXT DEFAULT (datetime('now')),
        UNIQUE(numero_controle_pncp, sequencial_termo))""",
    "CREATE INDEX IF NOT EXISTS ix_adit_ctrl ON contrato_aditivo(numero_controle_pncp)",
    """CREATE TABLE IF NOT EXISTS contrato_dossie (
        numero_controle_pncp TEXT PRIMARY KEY, dossie_json TEXT,
        montado_em TEXT DEFAULT (datetime('now')))""",
    """CREATE TABLE IF NOT EXISTS contrato_parecer (
        id INTEGER PRIMARY KEY AUTOINCREMENT, numero_controle_pncp TEXT,
        conclusao TEXT, score INTEGER, dimensoes_json TEXT, parecer_json TEXT,
        emitido_em TEXT DEFAULT (datetime('now')))""",
    """CREATE TABLE IF NOT EXISTS preco_referencia_cache (
        catmat TEXT PRIMARY KEY, mediana REAL, n INTEGER, minimo REAL, maximo REAL,
        atualizado_em TEXT DEFAULT (datetime('now')))""",
]


def init_schema(con: sqlite3.Connection) -> None:
    for ddl in DDL:
        con.execute(ddl)
    con.commit()
