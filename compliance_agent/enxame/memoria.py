# -*- coding: utf-8 -*-
"""Memória de veredito do enxame — inteligência progressiva, reusável.

Grava o veredito de cada dimensão/entidade em memoria_aprendizado e recupera o
histórico para injetar nas lentes ANTES de deliberar — para não re-acusar o que
a auditoria-ouro já refutou (lição dura: o RAG precisa carregar VEREDITOS, não
só normas). O loop llm/auto_melhoria consome essa memória semanalmente.
"""
from __future__ import annotations


def registrar_veredito(con, categoria: str, chave: str, veredito: str, score: int) -> None:
    """UPSERT por (categoria, chave); incrementa n_observacoes, guarda o último veredito."""
    row = con.execute(
        "select id, n_observacoes from memoria_aprendizado where categoria=? and chave=?",
        (categoria, chave)).fetchone()
    if row:
        con.execute(
            """update memoria_aprendizado set valor=?, confianca=?, n_observacoes=?,
                 ultima_vez=datetime('now') where id=?""",
            (veredito, float(score) / 10.0, (row[1] or 0) + 1, row[0]))
    else:
        con.execute(
            """insert into memoria_aprendizado (categoria, chave, valor, confianca, n_observacoes,
                 fonte, primeira_vez, ultima_vez)
               values (?,?,?,?,1,'enxame',datetime('now'),datetime('now'))""",
            (categoria, chave, veredito, float(score) / 10.0))
    con.commit()


def contexto_memoria(con, categoria: str, chave: str) -> str:
    """String para injetar na lente, ou '' se não há histórico."""
    try:
        row = con.execute(
            "select valor, n_observacoes from memoria_aprendizado where categoria=? and chave=?",
            (categoria, chave)).fetchone()
    except Exception:
        return ""
    if not row or not row[0]:
        return ""
    return (f"MEMÓRIA: esta dimensão/entidade já teve o veredito \"{row[0]}\" em "
            f"{row[1]} análise(s) anterior(es). Considere antes de re-acusar.")
