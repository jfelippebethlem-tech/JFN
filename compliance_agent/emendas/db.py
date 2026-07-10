# -*- coding: utf-8 -*-
"""Schema das emendas federais no compliance.db (aditivo, espelha pcrj/db.py).

POR QUE tabelas próprias: emenda tem chave natural (codigoEmenda) e valores nas
3 fases (empenhado/liquidado/pago) que NUNCA se somam — regra-mãe do projeto.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
_DB_PADRAO = _REPO / "data" / "compliance.db"

DDL = [
    """CREATE TABLE IF NOT EXISTS deputados_federais_rj (
        id_camara INTEGER PRIMARY KEY, nome TEXT NOT NULL, nome_norm TEXT NOT NULL,
        nome_civil TEXT, partido TEXT, uf TEXT DEFAULT 'RJ',
        legislaturas TEXT, situacao TEXT, coletado_em TEXT DEFAULT (datetime('now')))""",
    "CREATE INDEX IF NOT EXISTS ix_depfed_nome_norm ON deputados_federais_rj(nome_norm)",
    """CREATE TABLE IF NOT EXISTS emendas (
        codigo TEXT PRIMARY KEY, ano INTEGER NOT NULL,
        autor_raw TEXT, autor_norm TEXT, autor_id_camara INTEGER,
        tipo TEXT, e_pix INTEGER DEFAULT 0, funcao TEXT, subfuncao TEXT,
        localidade_gasto TEXT, uf_destino TEXT, municipio_destino_ibge TEXT,
        empenhado REAL, liquidado REAL, pago REAL,
        resto_inscrito REAL, resto_cancelado REAL, resto_pago REAL,
        recorte TEXT, fonte TEXT, coletado_em TEXT DEFAULT (datetime('now')))""",
    "CREATE INDEX IF NOT EXISTS ix_emendas_autor ON emendas(autor_norm)",
    "CREATE INDEX IF NOT EXISTS ix_emendas_uf ON emendas(uf_destino, ano)",
    """CREATE TABLE IF NOT EXISTS emenda_favorecidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo_emenda TEXT NOT NULL REFERENCES emendas(codigo),
        documento_favorecido TEXT, nome_favorecido TEXT,
        fase TEXT, documento_ref TEXT, valor REAL,
        coletado_em TEXT DEFAULT (datetime('now')),
        UNIQUE(codigo_emenda, documento_favorecido, fase, documento_ref))""",
    "CREATE INDEX IF NOT EXISTS ix_emfav_doc ON emenda_favorecidos(documento_favorecido)",
    """CREATE TABLE IF NOT EXISTS emendas_pix_planos (
        id_plano INTEGER PRIMARY KEY, codigo_plano TEXT, ano INTEGER,
        cnpj_beneficiario TEXT, nome_beneficiario TEXT, uf TEXT, municipio TEXT,
        situacao TEXT, valor_custeio REAL, valor_investimento REAL,
        payload_json TEXT, coletado_em TEXT DEFAULT (datetime('now')))""",
]


def conectar(db_path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(db_path) if db_path else _DB_PADRAO
    con = sqlite3.connect(str(p), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_schema(con: sqlite3.Connection) -> None:
    for ddl in DDL:
        con.execute(ddl)
    con.commit()


_COLS_EMENDA = ("codigo", "ano", "autor_raw", "autor_norm", "autor_id_camara", "tipo", "e_pix",
                "funcao", "subfuncao", "localidade_gasto", "uf_destino", "municipio_destino_ibge",
                "empenhado", "liquidado", "pago", "resto_inscrito", "resto_cancelado", "resto_pago",
                "recorte", "fonte")


def upsert_emenda(con: sqlite3.Connection, row: dict) -> None:
    vals = [row.get(c) for c in _COLS_EMENDA]
    sets = ",".join(f"{c}=excluded.{c}" for c in _COLS_EMENDA if c != "codigo")
    con.execute(
        f"INSERT INTO emendas ({','.join(_COLS_EMENDA)}) VALUES ({','.join('?' * len(_COLS_EMENDA))}) "
        f"ON CONFLICT(codigo) DO UPDATE SET {sets}", vals)
