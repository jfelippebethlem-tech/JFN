# -*- coding: utf-8 -*-
"""Camada de providers (Onda 12): consulta HOSPEDADA sob demanda — sem baixar base.

Cada FUNÇÃO (registry|sanctions|ownership|leaks|links) tem uma interface e múltiplos BACKENDS em ordem
de prioridade (base ungated primeiro, enricher gated depois). Fallback automático; cache SQLite com TTL
para respeitar rate limits (é cache, não base); toda resposta carrega proveniência (fonte+data+estado).

AGREGA — não substitui — os módulos enrich/* (opensanctions, aleph, midia_adversa, exif): a camada
providers oferece a interface unificada/robusta; os enrich seguem usáveis e podem ser backends aqui.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

_REPO = Path(__file__).resolve().parent.parent.parent


def agora_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


@dataclass
class Resultado:
    ok: bool
    dados: object  # dict | list | None
    fonte: str  # id do backend (ex.: "brasilapi")
    obtido_em: str  # ISO timestamp
    estado: str = "REAL"  # REAL | CACHE | INDISPONIVEL
    erro: str | None = None


class Backend(Protocol):
    id: str
    funcao: str  # registry|sanctions|ownership|leaks|links

    def disponivel(self) -> bool: ...
    def consultar(self, **q) -> Resultado: ...


class RateLimiter:
    """Intervalo mínimo entre chamadas por backend (respeita o limite do host)."""

    def __init__(self, rps: float):
        self._min = 1.0 / rps if rps > 0 else 0.0
        self._last = 0.0
        self._lock = threading.Lock()

    def aguardar(self) -> None:
        with self._lock:
            espera = self._min - (time.monotonic() - self._last)
            if espera > 0:
                time.sleep(espera)
            self._last = time.monotonic()


class CacheSQLite:
    """Cache de respostas (não é a base; é TTL local p/ poupar rate limit)."""

    def __init__(self, path: str | None = None):
        path = path or str(_REPO / "data" / "providers_cache.db")
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS cache "
            "(k TEXT PRIMARY KEY, fonte TEXT, obtido_em TEXT, ts REAL, dados TEXT)"
        )
        self._db.commit()
        self._lock = threading.Lock()

    def chave(self, escopo: str, q: dict) -> str:
        h = hashlib.sha256(json.dumps(q, sort_keys=True, default=str).encode()).hexdigest()[:16]
        return f"{escopo}:{h}"

    def get(self, k: str, ttl: int) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT fonte, obtido_em, ts, dados FROM cache WHERE k=?", (k,)
            ).fetchone()
        if not row:
            return None
        fonte, obtido_em, ts, dados = row
        if time.time() - ts > ttl:
            return None
        return {"fonte": fonte, "obtido_em": obtido_em, "dados": json.loads(dados)}

    def set(self, k: str, res: Resultado) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO cache VALUES (?,?,?,?,?)",
                (k, res.fonte, res.obtido_em, time.time(), json.dumps(res.dados, default=str)),
            )
            self._db.commit()


class Providers:
    def __init__(self, cache: CacheSQLite):
        self._backends: dict[str, list] = {}
        self._cache = cache

    def registrar(self, backend) -> None:
        self._backends.setdefault(backend.funcao, []).append(backend)

    def backends(self, funcao: str) -> list:
        return list(self._backends.get(funcao, []))

    def lookup(self, funcao: str, *, cache_ttl: int = 86400, **q) -> Resultado:
        """Primeiro backend que responder com sucesso (fallback em ordem)."""
        chave = self._cache.chave(funcao, q)
        c = self._cache.get(chave, cache_ttl)
        if c is not None:
            return Resultado(True, c["dados"], c["fonte"], c["obtido_em"], "CACHE")
        ultimo = None
        for b in self._backends.get(funcao, []):
            if not b.disponivel():
                continue
            res = b.consultar(**q)
            if res.ok:
                self._cache.set(chave, res)
                return res
            ultimo = res.erro
        return Resultado(False, None, "-", agora_iso(), "INDISPONIVEL",
                         ultimo or "nenhum backend disponivel")

    def lookup_all(self, funcao: str, *, cache_ttl: int = 86400, **q) -> list[Resultado]:
        """Consulta TODOS os backends disponíveis (triagem, ex.: sanções/idoneidade)."""
        out: list[Resultado] = []
        for b in self._backends.get(funcao, []):
            if not b.disponivel():
                continue
            chave = self._cache.chave(f"{funcao}@{b.id}", q)
            c = self._cache.get(chave, cache_ttl)
            if c is not None:
                out.append(Resultado(True, c["dados"], b.id, c["obtido_em"], "CACHE"))
                continue
            res = b.consultar(**q)
            if res.ok:
                self._cache.set(chave, res)
            out.append(res)
        return out
