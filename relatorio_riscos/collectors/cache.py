"""
Cache SQLite com TTL para resultados de coletores.

Evita chamadas repetidas às APIs para o mesmo CNPJ.
TTL padrão: 24 horas.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "coleta_cache.db"
_TTL_PADRAO = 86400  # 24 horas em segundos


def _get_conn() -> sqlite3.Connection:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_CACHE_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            chave     TEXT PRIMARY KEY,
            valor     TEXT NOT NULL,
            criado_em REAL NOT NULL,
            ttl       REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


def _chave(prefixo: str, *args) -> str:
    dados = prefixo + "|" + "|".join(str(a) for a in args)
    return hashlib.md5(dados.encode()).hexdigest()


def get(prefixo: str, *args) -> Optional[Any]:
    """Recupera valor do cache, retorna None se expirado ou ausente."""
    chave = _chave(prefixo, *args)
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT valor, criado_em, ttl FROM cache WHERE chave=?", (chave,)
        ).fetchone()
        conn.close()
        if row is None:
            return None
        valor_str, criado_em, ttl = row
        if time.time() - criado_em > ttl:
            return None  # expirado
        return json.loads(valor_str)
    except Exception as exc:
        logger.debug("Cache miss (erro): %s", exc)
        return None


def set(prefixo: str, valor: Any, *args, ttl: float = _TTL_PADRAO) -> None:
    """Armazena valor no cache."""
    chave = _chave(prefixo, *args)
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO cache (chave, valor, criado_em, ttl) VALUES (?,?,?,?)",
            (chave, json.dumps(valor, ensure_ascii=False, default=str), time.time(), ttl),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.debug("Erro ao salvar no cache: %s", exc)


def limpar_expirados() -> int:
    """Remove entradas expiradas. Retorna quantidade removida."""
    try:
        conn = _get_conn()
        agora = time.time()
        cur = conn.execute(
            "DELETE FROM cache WHERE (? - criado_em) > ttl", (agora,)
        )
        removidos = cur.rowcount
        conn.commit()
        conn.close()
        return removidos
    except Exception:
        return 0


def limpar_tudo() -> None:
    """Apaga todos os dados do cache."""
    try:
        conn = _get_conn()
        conn.execute("DELETE FROM cache")
        conn.commit()
        conn.close()
    except Exception:
        pass


def cached(prefixo: str, ttl: float = _TTL_PADRAO):
    """
    Decorator para cachear funções assíncronas.

    Uso:
        @cached("cnpj", ttl=3600)
        async def buscar_cnpj(cnpj: str) -> dict:
            ...
    """
    import functools

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = list(args) + [f"{k}={v}" for k, v in sorted(kwargs.items())]
            resultado = get(prefixo, *cache_key)
            if resultado is not None:
                logger.debug("Cache HIT: %s %s", prefixo, args)
                return resultado
            resultado = await func(*args, **kwargs)
            if resultado and resultado.get("ok", True):
                set(prefixo, resultado, *cache_key, ttl=ttl)
            return resultado

        return wrapper

    return decorator
