"""
SQLite FTS5 full-text search indexes for contracts, DOERJ publications, and alerts.

Uses the same database as the main SQLAlchemy models (compliance.db) but accesses
it via sqlite3 directly so that FTS5 virtual tables and triggers can be managed.
"""

import sqlite3
from pathlib import Path
from typing import Any

from compliance_agent.database.models import DB_PATH


def _get_conn() -> sqlite3.Connection:
    """Open a connection to the compliance database with row factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def criar_indices_fts():
    """
    Create FTS5 virtual tables and associated triggers for full-text search.

    Tables created:
      - fts_contratos  (content=contratos)
      - fts_doerj      (content=publicacoes_doerj)
      - fts_alertas    (content=alertas)

    Safe to call multiple times (uses IF NOT EXISTS).
    """
    conn = _get_conn()
    try:
        # ── fts_contratos ─────────────────────────────────────────────────────
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_contratos USING fts5(
                numero,
                objeto,
                orgao_contrat,
                modalidade,
                content=contratos,
                content_rowid=id
            )
        """)

        # Insert/Update/Delete triggers for contratos
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_contratos_ai
            AFTER INSERT ON contratos BEGIN
                INSERT INTO fts_contratos(rowid, numero, objeto, orgao_contrat, modalidade)
                VALUES (new.id, new.numero, new.objeto, new.orgao_contrat, new.modalidade);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_contratos_ad
            AFTER DELETE ON contratos BEGIN
                INSERT INTO fts_contratos(fts_contratos, rowid, numero, objeto, orgao_contrat, modalidade)
                VALUES ('delete', old.id, old.numero, old.objeto, old.orgao_contrat, old.modalidade);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_contratos_au
            AFTER UPDATE ON contratos BEGIN
                INSERT INTO fts_contratos(fts_contratos, rowid, numero, objeto, orgao_contrat, modalidade)
                VALUES ('delete', old.id, old.numero, old.objeto, old.orgao_contrat, old.modalidade);
                INSERT INTO fts_contratos(rowid, numero, objeto, orgao_contrat, modalidade)
                VALUES (new.id, new.numero, new.objeto, new.orgao_contrat, new.modalidade);
            END
        """)

        # ── fts_doerj ─────────────────────────────────────────────────────────
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_doerj USING fts5(
                titulo,
                texto,
                orgao,
                tipo_ato,
                content=publicacoes_doerj,
                content_rowid=id
            )
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_doerj_ai
            AFTER INSERT ON publicacoes_doerj BEGIN
                INSERT INTO fts_doerj(rowid, titulo, texto, orgao, tipo_ato)
                VALUES (new.id, new.titulo, new.texto, new.orgao, new.tipo_ato);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_doerj_ad
            AFTER DELETE ON publicacoes_doerj BEGIN
                INSERT INTO fts_doerj(fts_doerj, rowid, titulo, texto, orgao, tipo_ato)
                VALUES ('delete', old.id, old.titulo, old.texto, old.orgao, old.tipo_ato);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_doerj_au
            AFTER UPDATE ON publicacoes_doerj BEGIN
                INSERT INTO fts_doerj(fts_doerj, rowid, titulo, texto, orgao, tipo_ato)
                VALUES ('delete', old.id, old.titulo, old.texto, old.orgao, old.tipo_ato);
                INSERT INTO fts_doerj(rowid, titulo, texto, orgao, tipo_ato)
                VALUES (new.id, new.titulo, new.texto, new.orgao, new.tipo_ato);
            END
        """)

        # ── fts_alertas ───────────────────────────────────────────────────────
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_alertas USING fts5(
                titulo,
                descricao,
                tipo,
                severidade,
                content=alertas,
                content_rowid=id
            )
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_alertas_ai
            AFTER INSERT ON alertas BEGIN
                INSERT INTO fts_alertas(rowid, titulo, descricao, tipo, severidade)
                VALUES (new.id, new.titulo, new.descricao, new.tipo, new.severidade);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_alertas_ad
            AFTER DELETE ON alertas BEGIN
                INSERT INTO fts_alertas(fts_alertas, rowid, titulo, descricao, tipo, severidade)
                VALUES ('delete', old.id, old.titulo, old.descricao, old.tipo, old.severidade);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_alertas_au
            AFTER UPDATE ON alertas BEGIN
                INSERT INTO fts_alertas(fts_alertas, rowid, titulo, descricao, tipo, severidade)
                VALUES ('delete', old.id, old.titulo, old.descricao, old.tipo, old.severidade);
                INSERT INTO fts_alertas(rowid, titulo, descricao, tipo, severidade)
                VALUES (new.id, new.titulo, new.descricao, new.tipo, new.severidade);
            END
        """)

        conn.commit()

        # Rebuild indexes from existing data
        conn.execute("INSERT INTO fts_contratos(fts_contratos) VALUES('rebuild')")
        conn.execute("INSERT INTO fts_doerj(fts_doerj) VALUES('rebuild')")
        conn.execute("INSERT INTO fts_alertas(fts_alertas) VALUES('rebuild')")
        conn.commit()

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def buscar_contratos_fts(query: str, limite: int = 20) -> list[dict]:
    """
    Search contracts using FTS5 full-text index.

    Returns a list of dicts with: id, numero, objeto, orgao, valor, data, modalidade.
    """
    conn = _get_conn()
    results: list[dict] = []
    try:
        rows = conn.execute(
            """
            SELECT c.id, c.numero, c.objeto, c.orgao_contrat,
                   c.valor_total, c.data_assinatura, c.modalidade
            FROM fts_contratos
            JOIN contratos c ON fts_contratos.rowid = c.id
            WHERE fts_contratos MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limite),
        ).fetchall()
        for row in rows:
            results.append({
                "id":         row["id"],
                "numero":     row["numero"],
                "objeto":     row["objeto"],
                "orgao":      row["orgao_contrat"],
                "valor":      row["valor_total"],
                "data":       str(row["data_assinatura"]) if row["data_assinatura"] else None,
                "modalidade": row["modalidade"],
            })
    except Exception:
        pass
    finally:
        conn.close()
    return results


def buscar_doerj_fts(query: str, limite: int = 20) -> list[dict]:
    """
    Search DOERJ publications using FTS5 full-text index.

    Returns a list of dicts including a snippet excerpt from the matching text.
    """
    conn = _get_conn()
    results: list[dict] = []
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.titulo, p.orgao, p.tipo_ato, p.data_publicacao,
                   snippet(fts_doerj, 1, '<b>', '</b>', '...', 32) AS excerpt
            FROM fts_doerj
            JOIN publicacoes_doerj p ON fts_doerj.rowid = p.id
            WHERE fts_doerj MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limite),
        ).fetchall()
        for row in rows:
            results.append({
                "id":    row["id"],
                "titulo": row["titulo"],
                "orgao": row["orgao"],
                "tipo":  row["tipo_ato"],
                "data":  str(row["data_publicacao"]) if row["data_publicacao"] else None,
                "excerpt": row["excerpt"],
            })
    except Exception:
        pass
    finally:
        conn.close()
    return results


def buscar_alertas_fts(query: str, limite: int = 20) -> list[dict]:
    """
    Search alerts using FTS5 full-text index.

    Returns a list of dicts with: id, titulo, descricao, tipo, severidade.
    """
    conn = _get_conn()
    results: list[dict] = []
    try:
        rows = conn.execute(
            """
            SELECT a.id, a.titulo, a.descricao, a.tipo, a.severidade, a.created_at
            FROM fts_alertas
            JOIN alertas a ON fts_alertas.rowid = a.id
            WHERE fts_alertas MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limite),
        ).fetchall()
        for row in rows:
            results.append({
                "id":         row["id"],
                "titulo":     row["titulo"],
                "descricao":  row["descricao"],
                "tipo":       row["tipo"],
                "severidade": row["severidade"],
                "criado_em":  str(row["created_at"]) if row["created_at"] else None,
            })
    except Exception:
        pass
    finally:
        conn.close()
    return results
