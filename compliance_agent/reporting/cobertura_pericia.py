# -*- coding: utf-8 -*-
"""Cobertura da perícia documental — quanto do acervo já recebeu JUÍZO, e por quem.

Por que existe. Até 2026-08-03 o número só existia para quem abrisse o SQLite: **39 processos de
2.082** tinham juízo por documento na rubrica vigente. O painel mostrava achados e fila do fiscal
sem dizer que 98% do acervo nunca fora periciado documento a documento — e um painel que não
mostra a própria cobertura deixa a impressão contrária.

Três números, e nenhum sozinho: **quanto** (processos e documentos), **por quem** (a cadeia de
LLM que produziu o veredito — procedência é o que permite auditar uma queda de qualidade depois)
e **o quê** (a distribuição de escala; "3 documentos julgados" não diz se algum é problemático).

Honestidade: base ausente devolve `indisponivel`, nunca 0% — zero afirmaria cobertura nula onde
não houve medição.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

_DB = Path(__file__).resolve().parents[2] / "data" / "compliance.db"


def medir(*, db: str | Path | None = None, rubrica: str | None = None) -> dict[str, Any]:
    """Cobertura medida. `rubrica` default = a vigente do `doc_juizo`."""
    if rubrica is None:
        from compliance_agent.sei.doc_juizo import RUBRICA_VERSAO
        rubrica = RUBRICA_VERSAO
    caminho = Path(db) if db else _DB
    if not caminho.exists():
        return {"indisponivel": True, "motivo": "compliance.db ausente nesta máquina",
                "rubrica": rubrica, "pct": None}
    try:
        con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return {"indisponivel": True, "motivo": str(e)[:120], "rubrica": rubrica, "pct": None}
    try:
        avaliados = con.execute("select count(*) from processo_avaliacao").fetchone()[0]
        com_juizo = con.execute(
            "select count(distinct numero_sei) from doc_veredito where rubrica_versao=?",
            (rubrica,)).fetchone()[0]
        docs = con.execute("select count(*) from doc_veredito where rubrica_versao=?",
                           (rubrica,)).fetchone()[0]
        por_cadeia = {str(m or "?"): n for m, n in con.execute(
            "select modelo, count(*) from doc_veredito where rubrica_versao=? group by 1"
            " order by 2 desc", (rubrica,))}
        por_escala = {("null" if e is None else str(e)): n for e, n in con.execute(
            "select escala, count(*) from doc_veredito where rubrica_versao=? group by 1"
            " order by 1", (rubrica,))}
        ultimo = con.execute(
            "select max(avaliado_em) from doc_veredito where rubrica_versao=?",
            (rubrica,)).fetchone()[0]
    except sqlite3.Error as e:
        return {"indisponivel": True, "motivo": str(e)[:120], "rubrica": rubrica, "pct": None}
    finally:
        con.close()
    return {
        "indisponivel": False, "rubrica": rubrica,
        "processos_avaliados": avaliados, "processos_com_juizo": com_juizo,
        "processos_pendentes": max(0, avaliados - com_juizo),
        "documentos_julgados": docs,
        "pct": round(100.0 * com_juizo / avaliados, 1) if avaliados else None,
        "por_cadeia": por_cadeia, "por_escala": por_escala, "ultimo_juizo": ultimo,
        "_nota": ("Cobertura da perícia documento a documento na rubrica vigente. Processo sem "
                  "juízo NÃO é processo regular: é processo ainda não periciado — "
                  "INDISPONÍVEL ≠ 0."),
    }
