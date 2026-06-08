# -*- coding: utf-8 -*-
"""Corpus de editais/processos — JFN 2.0, Onda 5. Índice full-text (SQLite FTS5, nativo/grátis).

Persiste o texto dos editais já baixados (PNCP/SEI) para busca textual rápida e para não
re-baixar. Embeddings semânticos (sentence-transformers CPU) ficam como evolução opcional —
o piso é FTS5, que já cobre "uma vez lido, buscar direcionamento". Honesto: só indexa o que leu.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(str(_DB))
    con.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS corpus_editais "
        "USING fts5(ref UNINDEXED, objeto, texto, meta UNINDEXED)")
    return con


def indexar(ref: str, texto: str, objeto: str = "", meta: str = "") -> bool:
    """Indexa (ou re-indexa) um edital pelo ref (id_pncp/numero SEI). Idempotente."""
    if not (texto or "").strip():
        return False
    con = _con()
    try:
        con.execute("DELETE FROM corpus_editais WHERE ref=?", (ref,))
        con.execute("INSERT INTO corpus_editais (ref, objeto, texto, meta) VALUES (?,?,?,?)",
                    (ref, objeto or "", texto, meta or ""))
        con.commit()
        return True
    finally:
        con.close()


def buscar(consulta: str, limite: int = 20) -> list[dict]:
    """Busca full-text no corpus. Retorna [{ref, objeto, trecho}] ranqueado por relevância."""
    if not (consulta or "").strip():
        return []
    con = _con()
    try:
        try:
            rows = con.execute(
                "SELECT ref, objeto, snippet(corpus_editais, 2, '[', ']', ' … ', 12) "
                "FROM corpus_editais WHERE corpus_editais MATCH ? ORDER BY rank LIMIT ?",
                (consulta, limite)).fetchall()
        except sqlite3.OperationalError:
            return []
        return [{"ref": r[0], "objeto": r[1], "trecho": r[2]} for r in rows]
    finally:
        con.close()


def stats() -> dict:
    con = _con()
    try:
        n = con.execute("SELECT COUNT(*) FROM corpus_editais").fetchone()[0]
    finally:
        con.close()
    return {"n_editais_indexados": n}
