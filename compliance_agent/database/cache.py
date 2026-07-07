"""
SQLite-backed cache with TTL support for API responses.

Stores serialized values in a dedicated SQLite database at data/api_cache.db,
allowing expensive API calls to be cached and reused across runs.
"""

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

CACHE_DB_PATH = Path("data/api_cache.db")


def _get_conn() -> sqlite3.Connection:
    """Open (or create) the cache database and ensure the table exists."""
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CACHE_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            key       TEXT PRIMARY KEY,
            value     TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_cache_expires ON cache(expires_at)")
    conn.commit()
    return conn


def get(key: str) -> Optional[Any]:
    """
    Retrieve a cached value by key.

    Returns None if the key does not exist or the entry has expired.
    """
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
        conn.close()
        if row is None:
            return None
        value_json, expires_at = row
        if time.time() > expires_at:
            # Expired
            return None
        return json.loads(value_json)
    except Exception:
        return None


def set(key: str, value: Any, ttl_hours: float = 24):
    """
    Store a value in the cache with the given TTL.

    Uses INSERT OR REPLACE to overwrite existing entries.
    """
    try:
        conn = _get_conn()
        expires_at = time.time() + ttl_hours * 3600
        conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False, default=str), expires_at),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("falha ao gravar cache %s (API cara será re-chamada): %s", key, exc)


def delete(key: str):
    """Remove a specific key from the cache."""
    try:
        conn = _get_conn()
        conn.execute("DELETE FROM cache WHERE key = ?", (key,))
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.debug("falha ao remover chave %s do cache: %s", key, exc)


def purge_expired():
    """Remove all expired entries from the cache."""
    try:
        conn = _get_conn()
        conn.execute("DELETE FROM cache WHERE expires_at <= ?", (time.time(),))
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.debug("falha ao expurgar cache expirado: %s", exc)


def stats() -> dict:
    """Return cache statistics: total entries, expired, and active."""
    try:
        conn = _get_conn()
        now = time.time()
        total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        expiradas = conn.execute(
            "SELECT COUNT(*) FROM cache WHERE expires_at <= ?", (now,)
        ).fetchone()[0]
        conn.close()
        return {
            "total_entradas": total,
            "expiradas": expiradas,
            "ativas": total - expiradas,
        }
    except Exception:
        return {"total_entradas": 0, "expiradas": 0, "ativas": 0}
