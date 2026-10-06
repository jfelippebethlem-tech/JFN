# -*- coding: utf-8 -*-
"""Schema do enxame de contratos no compliance.db (aditivo)."""
from __future__ import annotations

import logging
import sqlite3

from compliance_agent.emendas.db import conectar

logger = logging.getLogger(__name__)

__all__ = ["conectar", "init_schema", "DDL"]

DDL = [
    """CREATE TABLE IF NOT EXISTS contrato_aditivo (
        id INTEGER PRIMARY KEY AUTOINCREMENT, numero_controle_pncp TEXT NOT NULL,
        sequencial_termo INTEGER, numero_termo TEXT, objeto TEXT,
        valor_acrescido REAL, valor_global REAL, prazo_aditado_dias INTEGER,
        vigencia_fim TEXT, qualif_acrescimo TEXT, qualif_vigencia TEXT, qualif_reajuste TEXT,
        fundamento_legal TEXT, data_assinatura TEXT, tipo_termo TEXT, processo TEXT,
        coletado_em TEXT DEFAULT (datetime('now')),
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
    # Migração ADITIVA. O coletor jogava fora três campos que o PNCP entrega e que decidem a
    # leitura de um aditivo: `dataAssinatura` (sem ela não há como medir se o acréscimo veio logo
    # após a assinatura do contrato — o sinal que a CGE usou no caso da SECID, aditivo de 45,4% em
    # 17 dias, e que era INCALCULÁVEL nos 1.729 aditivos já coletados), `tipoTermoContratoNome`
    # (a própria fonte classifica o termo, e a régua do art. 125 depende da natureza) e o número
    # do `processo`, que é a ponte para os autos no SEI.
    for col in ("data_assinatura TEXT", "tipo_termo TEXT", "processo TEXT"):
        try:
            con.execute(f"ALTER TABLE contrato_aditivo ADD COLUMN {col}")
        except sqlite3.OperationalError as exc:
            # coluna já existe é o caso NORMAL da segunda execução — mas silêncio aqui esconderia
            # também um erro real de schema, e a catraca de except-pass da casa existe por isso.
            logger.debug("migração de contrato_aditivo: %s (%s)", col, exc)
    con.commit()
