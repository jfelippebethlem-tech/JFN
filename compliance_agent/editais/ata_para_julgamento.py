# -*- coding: utf-8 -*-
"""Ponte ata_documento (PNCP/OCR) → certame_julgamento.

O coletor `collectors/atas_julgamento` guarda o TEXTO cru das atas em `ata_documento`,
mas o motor de decisões (`detectores/coletor_ata`) só rodava sobre leituras do SEI —
duas trilhas desconectadas: certame com ata no PNCP nunca recebia classificação de
inabilitação/trivialidade e a família `certame_ata` do índice ficava INDISPONÍVEL.
Esta ponte converte as linhas de `ata_documento` no formato `leitura` que
`montar_ctx_julgamento` espera e persiste via `persistir_julgamento` (reuso integral
dos regexes e da doutrina por licitante — nada novo de parsing aqui).
"""
from __future__ import annotations

import sqlite3


def leitura_de_ata_documento(rows: list[sqlite3.Row | tuple]) -> dict:
    """(titulo, texto)[] → `leitura` mínima no formato do sei_reader (só o que o coletor usa)."""
    return {
        "numero": None,
        "texto": "",
        "documentos": [],
        "conteudo_documentos": [{"doc": t or "Ata de julgamento (PNCP)", "conteudo": x or ""}
                                for t, x in rows],
    }


def julgar_certame(con: sqlite3.Connection, certame: str) -> dict | None:
    """Roda o motor de decisões sobre as atas PNCP de UM certame e persiste. None = ata ilegível
    (sem decisão extraível — honesto, não grava vazio)."""
    from compliance_agent.detectores.coletor_ata import persistir_julgamento

    rows = con.execute("SELECT titulo, texto FROM ata_documento WHERE certame=?",
                       (certame,)).fetchall()
    if not rows:
        return None
    return persistir_julgamento(leitura_de_ata_documento([tuple(r) for r in rows]), certame, con)


def backfill(con: sqlite3.Connection | None = None, *, limite: int | None = None,
             so_pendentes: bool = True) -> dict:
    """Todas as atas PNCP sem julgamento persistido → certame_julgamento. Serial e leve
    (sqlite + regex local). Retorna contadores; certames tocados em `certames` p/ o chamador
    recalcular o índice (indice_certame.calcular_e_persistir)."""
    from compliance_agent.editais.db import conectar, init_schema

    fechar = con is None
    con = con or conectar()
    init_schema(con)
    try:
        sql = "SELECT DISTINCT certame FROM ata_documento"
        if so_pendentes:
            sql += " WHERE certame NOT IN (SELECT certame FROM certame_julgamento)"
        certames = [r[0] for r in con.execute(sql).fetchall()]
        if limite:
            certames = certames[:limite]
        stats = {"candidatos": len(certames), "persistidos": 0, "sem_resultado": 0, "erro": 0}
        tocados = []
        for c in certames:
            try:
                agg = julgar_certame(con, c)
            except Exception:  # noqa: BLE001 — 1 ata ruim não derruba o backfill
                stats["erro"] += 1
                continue
            if agg is None:
                stats["sem_resultado"] += 1
            else:
                stats["persistidos"] += 1
                tocados.append(c)
        stats["certames"] = tocados
        return stats
    finally:
        if fechar:
            con.close()
