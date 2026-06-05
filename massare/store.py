# -*- coding: utf-8 -*-
"""
Massare — sede de agregação de dados de mercado (SQLite).

Um único arquivo `massare/data/massare.db` concentra TODA a série histórica usada
pelo Massare para rodar e validar análises/teses. Robusto, consultável por SQL, sem
dependência externa (sqlite3 é stdlib). Tabelas:

  prices(symbol, date, open, high, low, close, adj_close, volume, source)  -- OHLCV diário
  macro(series, date, value, source)                                       -- séries macro (juros, câmbio, inflação)
  assets(symbol, name, kind, region, currency, source)                     -- universo/catálogo
  meta(key, value)                                                         -- carimbos (última atualização etc.)

Tudo upsert (idempotente): rodar de novo não duplica, só completa/atualiza.
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("MASSARE_DB", Path(__file__).resolve().parent / "data" / "massare.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    symbol     TEXT NOT NULL,
    date       TEXT NOT NULL,           -- YYYY-MM-DD
    open       REAL, high REAL, low REAL, close REAL, adj_close REAL,
    volume     REAL,
    source     TEXT,
    PRIMARY KEY (symbol, date)
);
CREATE INDEX IF NOT EXISTS ix_prices_symbol ON prices(symbol);
CREATE INDEX IF NOT EXISTS ix_prices_date   ON prices(date);

CREATE TABLE IF NOT EXISTS macro (
    series TEXT NOT NULL,
    date   TEXT NOT NULL,
    value  REAL,
    source TEXT,
    PRIMARY KEY (series, date)
);

CREATE TABLE IF NOT EXISTS assets (
    symbol   TEXT PRIMARY KEY,
    name     TEXT, kind TEXT, region TEXT, currency TEXT, source TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=30)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    with connect() as con:
        con.executescript(SCHEMA)


def upsert_prices(rows, source):
    """rows: iterável de dicts com date/open/high/low/close/adj_close/volume e 'symbol'."""
    sql = """INSERT INTO prices(symbol,date,open,high,low,close,adj_close,volume,source)
             VALUES(:symbol,:date,:open,:high,:low,:close,:adj_close,:volume,:source)
             ON CONFLICT(symbol,date) DO UPDATE SET
               open=excluded.open, high=excluded.high, low=excluded.low,
               close=excluded.close, adj_close=excluded.adj_close,
               volume=excluded.volume, source=excluded.source"""
    n = 0
    with connect() as con:
        for r in rows:
            r = {**r, "source": source}
            for k in ("open", "high", "low", "close", "adj_close", "volume"):
                r.setdefault(k, None)
            con.execute(sql, r)
            n += 1
    return n


def upsert_macro(series, rows, source):
    """rows: iterável de (date, value)."""
    sql = """INSERT INTO macro(series,date,value,source) VALUES(?,?,?,?)
             ON CONFLICT(series,date) DO UPDATE SET value=excluded.value, source=excluded.source"""
    n = 0
    with connect() as con:
        for d, v in rows:
            con.execute(sql, (series, d, v, source))
            n += 1
    return n


def upsert_asset(symbol, name, kind, region, currency, source):
    with connect() as con:
        con.execute(
            """INSERT INTO assets(symbol,name,kind,region,currency,source) VALUES(?,?,?,?,?,?)
               ON CONFLICT(symbol) DO UPDATE SET name=excluded.name, kind=excluded.kind,
               region=excluded.region, currency=excluded.currency, source=excluded.source""",
            (symbol, name, kind, region, currency, source),
        )


def set_meta(key, value):
    with connect() as con:
        con.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(value)))


def coverage():
    """Resumo: por símbolo, nº de pregões e intervalo de datas."""
    with connect() as con:
        rows = con.execute(
            """SELECT symbol, COUNT(*) n, MIN(date) d0, MAX(date) d1
               FROM prices GROUP BY symbol ORDER BY symbol"""
        ).fetchall()
        macro = con.execute("SELECT series, COUNT(*) n, MIN(date), MAX(date) FROM macro GROUP BY series").fetchall()
    return rows, macro


if __name__ == "__main__":
    init_db()
    px, mac = coverage()
    print(f"DB: {DB_PATH}")
    print(f"Símbolos de preço: {len(px)}")
    for s, n, d0, d1 in px:
        print(f"  {s:12} {n:6} pregões  {d0} → {d1}")
    print(f"Séries macro: {len(mac)}")
    for s, n, d0, d1 in mac:
        print(f"  {s:18} {n:6}  {d0} → {d1}")
