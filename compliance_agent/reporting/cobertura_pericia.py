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
        # DENOMINADOR: só o que é PERICIÁVEL. Processo cuja captura não dá para avaliar
        # (`NAO_AVALIAVEL`) não está pendente de PERÍCIA, está pendente de CAPTURA — e são duas
        # filas diferentes, com donos diferentes. Somá-las mostrava 2.174 pendentes quando 234
        # deles não têm texto para julgar; a fila da captura tem cartão próprio desde
        # 2026-08-04 (`reporting/cobertura_captura`). Misturar as duas faz o número da perícia
        # parecer pior do que é e some com a razão real do atraso.
        # Degrada para o total quando a coluna não existe (esquema antigo/teste): perder a
        # separação das duas filas é aceitável; perder a MEDIÇÃO INTEIRA por uma coluna, não.
        try:
            periciaveis = con.execute(
                "select count(*) from processo_avaliacao "
                "where faixa is null or faixa != 'NAO_AVALIAVEL'").fetchone()[0]
        except sqlite3.Error:
            periciaveis = avaliados
        sem_captura = max(0, avaliados - periciaveis)
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
        "processos_avaliados": avaliados, "processos_periciaveis": periciaveis,
        "processos_sem_captura": sem_captura, "processos_com_juizo": com_juizo,
        "processos_pendentes": max(0, periciaveis - com_juizo),
        "documentos_julgados": docs,
        "pct": round(100.0 * com_juizo / periciaveis, 1) if periciaveis else None,
        "por_cadeia": por_cadeia, "por_escala": por_escala, "ultimo_juizo": ultimo,
        "_nota": ("Cobertura da perícia documento a documento na rubrica vigente, sobre os "
                  "processos PERICIÁVEIS. Processo sem juízo NÃO é processo regular: é processo "
                  "ainda não periciado — INDISPONÍVEL ≠ 0. Os sem captura utilizável estão numa "
                  "fila diferente, com dono diferente (ver /api/captura/cobertura)."),
    }
