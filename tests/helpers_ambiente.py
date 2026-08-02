# -*- coding: utf-8 -*-
"""Um lugar só para responder "este ambiente TEM os dados que o teste precisa?".

Existir o arquivo não basta: o runner do CI cria uma `compliance.db` VAZIA (testes que escrevem
a criam), e todo guard escrito como `DB.exists()` deixava o teste rodar contra um banco sem
tabelas — falha de ambiente que o `ci_delta` lia como REGRESSÃO. Mesmo vício da corrida da
árvore do SEI: **checar presença quando o que importa é conteúdo** (2026-08-02).

Use em teste novo:

    from helpers_ambiente import base_utilizavel
    pytestmark = pytest.mark.skipif(not base_utilizavel(), reason="sem compliance.db real")
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_MIN_BYTES = 1_000_000     # base embrionária (criada por teste) não passa disto
_MIN_TABELAS = 20          # a base real tem dezenas; a de fachada, poucas


def base_utilizavel(caminho: str | Path | None = None) -> bool:
    """A `compliance.db` deste ambiente serve para consultar dado real?"""
    if caminho is None:
        try:
            from compliance_agent.reporting.intel_base import _DB
        except Exception:
            return False
        caminho = _DB
    p = Path(caminho)
    if not p.exists() or p.stat().st_size < _MIN_BYTES:
        return False
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            n = con.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return n >= _MIN_TABELAS


def acervo_sei_utilizavel(minimo: int = 1) -> bool:
    """Há processos ARQUIVADOS com texto? (o diretório existir não diz nada — ele nasce vazio)"""
    base = Path(__file__).resolve().parents[1] / "data" / "sei_arquivo"
    if not base.is_dir():
        return False
    achados = 0
    for man in base.glob("*/manifest.json"):
        achados += 1
        if achados >= minimo:
            return True
    return False
