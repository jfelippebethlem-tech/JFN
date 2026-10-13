#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Salva o que é LEGÍVEL de uma tabela com páginas corrompidas — e MEDE o que se perdeu.

POR QUE EXISTE (2026-08-12). O `PRAGMA integrity_check` de `data/compliance.db` acusou quatro
árvores danificadas: a TABELA `ordens_bancarias` (rootpage 7, 155 ocorrências de *invalid page
number*) e três índices de `ob_orcamentaria_siafe`. `COUNT(*)` responde, mas ler a coluna `valor`
devolve *database disk image is malformed* — o dano está nas páginas de dado.

Não é o caso conhecido da casa (`-shm` morto no processo, que se cura com restart): ali o
`quick_check` volta `ok`. Aqui não volta, e a própria nota diz o que fazer quando não volta —
*"perícia de dado, não reboot"*.

Esta ferramenta é a perícia: varre por faixas de `rowid`, subdivide quando a faixa estoura, e
isola as linhas ilegíveis UMA A UMA. Assim o prejuízo deixa de ser "a tabela está corrompida" e
passa a ser um número — quantas linhas, quais rowids, quanto valor.

NÃO ESCREVE NO BANCO DE ORIGEM. Abre em `mode=ro` e grava a salvação num arquivo novo.

    .venv/bin/python -m tools.salvar_tabela_corrompida ordens_bancarias --saida data/salvo.db
    .venv/bin/python -m tools.salvar_tabela_corrompida ordens_bancarias --so-medir
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"


def _abrir_ro(caminho: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=180)


def varrer(con: sqlite3.Connection, tabela: str, *, passo: int = 2000,
           destino: sqlite3.Connection | None = None) -> dict:
    """Percorre a tabela por faixas de rowid. Faixa que estoura é subdividida até a linha.

    O passo grande é de propósito: a leitura boa é o caso comum, e subdividir só o que quebra
    mantém o custo perto de uma varredura normal. Sem isso, ler 1,16 milhão de linhas uma a uma
    numa VM de 2 vCPU levaria horas para medir o que 155 páginas estragaram.
    """
    lo, hi = con.execute(  # noqa: S608 — nome de tabela vem do operador, não da rede
        f"SELECT MIN(rowid), MAX(rowid) FROM {tabela}").fetchone()
    if lo is None:
        return {"ok": True, "lidas": 0, "perdidas": 0, "rowids_perdidos": []}
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({tabela})")]
    ins = (f"INSERT OR REPLACE INTO {tabela} ({','.join(cols)}) "  # noqa: S608
           f"VALUES ({','.join('?' * len(cols))})") if destino else None
    lidas = 0
    perdidos: list[int] = []
    pilha = [(lo, hi)]
    while pilha:
        a, b = pilha.pop()
        if b - a + 1 > passo:
            meio = (a + b) // 2
            pilha.append((meio + 1, b))
            pilha.append((a, meio))
            continue
        try:
            linhas = con.execute(
                f"SELECT {','.join(cols)} FROM {tabela} "  # noqa: S608
                f"WHERE rowid BETWEEN ? AND ?", (a, b)).fetchall()
        except sqlite3.DatabaseError:
            if a == b:
                perdidos.append(a)          # a linha em si é ilegível
                continue
            meio = (a + b) // 2
            pilha.append((meio + 1, b))
            pilha.append((a, meio))
            continue
        lidas += len(linhas)
        if destino is not None and linhas:
            destino.executemany(ins, linhas)
    return {"ok": True, "lidas": lidas, "perdidas": len(perdidos),
            "rowids_perdidos": sorted(perdidos)[:200]}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("tabela")
    ap.add_argument("--db", default=str(_DB))
    ap.add_argument("--saida", default="", help="banco novo com o que foi salvo")
    ap.add_argument("--so-medir", action="store_true", help="não grava nada; só conta o prejuízo")
    ap.add_argument("--passo", type=int, default=2000)
    a = ap.parse_args(argv)

    con = _abrir_ro(Path(a.db))
    destino = None
    if a.saida and not a.so_medir:
        destino = sqlite3.connect(a.saida, timeout=180)
        ddl = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                          (a.tabela,)).fetchone()
        if not ddl or not ddl[0]:
            print(f"tabela {a.tabela} não existe em {a.db}"); return 1
        destino.execute(f"DROP TABLE IF EXISTS {a.tabela}")  # noqa: S608
        destino.execute(ddl[0])
    try:
        r = varrer(con, a.tabela, passo=a.passo, destino=destino)
        if destino:
            destino.commit()
    finally:
        con.close()
        if destino:
            destino.close()
    total = r["lidas"] + r["perdidas"]
    pct = (100.0 * r["perdidas"] / total) if total else 0.0
    print(f"{a.tabela}: {r['lidas']:,} linhas salvas · {r['perdidas']:,} ILEGÍVEIS "
          f"({pct:.4f}%)".replace(",", "."))
    if r["rowids_perdidos"]:
        print(f"  primeiros rowids perdidos: {r['rowids_perdidos'][:12]}")
    if a.saida and not a.so_medir:
        print(f"  gravado em {a.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
