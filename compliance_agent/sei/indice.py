# -*- coding: utf-8 -*-
"""Índice COMPACTO da varredura do SEI (Onda G) — preparo p/ varrer o SEI de cada OB (~41k) sem estourar a VM.

Decisões de storage (pedido do dono: arquivos pequenos, cabe na VM 50GB):
- SQLite DEDICADO `data/sei_indice.db` (NÃO o compliance.db → zero contenção de lock com o sweep SIAFE).
- Persistir SÓ o dado ESTRUTURADO (processo, documentos, relacionados, itens de preço). ~1–3 KB/processo.
- NUNCA guardar os PDFs/HTML a longo prazo: cache curto em data/sei_cache/, podado após extração (`podar_cache`).
- Idempotente (chave = número do processo / url do doc). Proveniência: data da leitura + fonte.

Escala estimada: 41k processos × ~2 KB ≈ ~80–120 MB. WAL p/ leituras concorrentes.
"""
from __future__ import annotations

import gzip
import json
import sqlite3
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
_DB = _REPO / "data" / "sei_indice.db"
_CACHE = _REPO / "data" / "sei_cache"


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB))
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db(c: sqlite3.Connection | None = None) -> None:
    own = c is None
    c = c or conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS sei_processo (
        numero TEXT PRIMARY KEY, objeto TEXT, tipo_processo TEXT, n_docs INTEGER, n_relacionados INTEGER,
        n_itens INTEGER, lido_em REAL, ok INTEGER, erro TEXT);
    CREATE TABLE IF NOT EXISTS sei_documento (
        processo TEXT, titulo TEXT, tipo TEXT, formato TEXT, url TEXT,
        PRIMARY KEY (processo, url));
    CREATE TABLE IF NOT EXISTS sei_relacionado (
        processo TEXT, relacionado TEXT, titulo TEXT, url TEXT,
        PRIMARY KEY (processo, url));
    CREATE TABLE IF NOT EXISTS sei_item_preco (
        processo TEXT, doc TEXT, tipo_doc TEXT, descricao TEXT, unidade TEXT, quantidade REAL,
        valor_unitario REAL, valor_total REAL, fornecedor TEXT, cnpj TEXT, metodo TEXT, confianca REAL);
    CREATE INDEX IF NOT EXISTS ix_doc_proc ON sei_documento(processo);
    CREATE INDEX IF NOT EXISTS ix_rel_proc ON sei_relacionado(processo);
    CREATE INDEX IF NOT EXISTS ix_item_proc ON sei_item_preco(processo);
    CREATE INDEX IF NOT EXISTS ix_item_cnpj ON sei_item_preco(cnpj);
    """)
    c.commit()
    if own:
        c.close()


def persistir(numero: str, *, objeto: str = "", tipo_processo: str = "", docs: list | None = None,
              relacionados: list | None = None, itens: list | None = None, ok: bool = True,
              erro: str = "", c: sqlite3.Connection | None = None) -> dict:
    """Grava (idempotente) o resultado COMPACTO de um processo. docs/relacionados/itens = listas de dicts.
    Não grava PDFs — só os campos estruturados. Retorna {numero, n_docs, n_relacionados, n_itens}."""
    own = c is None
    c = c or conn()
    init_db(c)
    docs = docs or []
    relacionados = relacionados or []
    itens = itens or []
    c.execute("INSERT OR REPLACE INTO sei_processo VALUES (?,?,?,?,?,?,?,?,?)",
              (numero, objeto[:500], tipo_processo, len(docs), len(relacionados), len(itens),
               time.time(), 1 if ok else 0, erro[:300]))
    c.execute("DELETE FROM sei_documento WHERE processo=?", (numero,))
    for d in docs:
        c.execute("INSERT OR REPLACE INTO sei_documento VALUES (?,?,?,?,?)",
                  (numero, (d.get("titulo") or "")[:200], d.get("tipo") or "", d.get("formato") or "",
                   d.get("url") or ""))
    c.execute("DELETE FROM sei_relacionado WHERE processo=?", (numero,))
    for r in relacionados:
        c.execute("INSERT OR REPLACE INTO sei_relacionado VALUES (?,?,?,?)",
                  (numero, (r.get("numero") or "")[:60], (r.get("titulo") or "")[:160], r.get("url") or ""))
    c.execute("DELETE FROM sei_item_preco WHERE processo=?", (numero,))
    for it in itens:
        c.execute("INSERT INTO sei_item_preco VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (numero, (it.get("doc") or "")[:120], it.get("tipo_doc") or "", (it.get("descricao") or "")[:300],
                   it.get("unidade") or "", it.get("quantidade"), it.get("valor_unitario"), it.get("valor_total"),
                   (it.get("fornecedor") or "")[:160], it.get("cnpj") or "", it.get("metodo") or "", it.get("confianca")))
    c.commit()
    if own:
        c.close()
    return {"numero": numero, "n_docs": len(docs), "n_relacionados": len(relacionados), "n_itens": len(itens)}


def ja_indexado(numero: str, c: sqlite3.Connection | None = None) -> bool:
    """True se o processo já foi lido com sucesso (p/ o sweep ser resumível e não reprocessar)."""
    own = c is None
    c = c or conn()
    init_db(c)
    row = c.execute("SELECT ok FROM sei_processo WHERE numero=?", (numero,)).fetchone()
    if own:
        c.close()
    return bool(row and row[0])


def stats() -> dict:
    c = conn()
    init_db(c)
    try:
        p = c.execute("SELECT COUNT(*), SUM(ok) FROM sei_processo").fetchone()
        itens = c.execute("SELECT COUNT(*) FROM sei_item_preco").fetchone()[0]
        rel = c.execute("SELECT COUNT(*) FROM sei_relacionado").fetchone()[0]
        tam = _DB.stat().st_size if _DB.exists() else 0
        return {"processos": p[0] or 0, "ok": p[1] or 0, "itens_preco": itens, "relacionados": rel,
                "db_bytes": tam, "db_mb": round(tam / 1e6, 1)}
    finally:
        c.close()


def podar_cache(idade_horas: float = 24.0) -> int:
    """Remove arquivos de cache SEI (PDF/HTML/json brutos) mais velhos que `idade_horas` — storage-safe.
    O índice (sei_indice.db) já tem o dado estruturado; o bruto é regenerável. Retorna nº de arquivos removidos."""
    if not _CACHE.exists():
        return 0
    corte = time.time() - idade_horas * 3600
    n = 0
    for f in _CACHE.glob("**/*"):
        if f.is_file() and f.suffix.lower() in (".pdf", ".html", ".htm") and f.stat().st_mtime < corte:
            try:
                f.unlink(); n += 1
            except OSError:
                pass
    return n
