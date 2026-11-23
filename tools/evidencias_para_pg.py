# -*- coding: utf-8 -*-
"""Cópia do SQLite `data/evidencias.db` para o PostgreSQL da VM-2 (docs/PLANO-PLATAFORMA-EVIDENCIAS.md, Fase 3).

As 9 tabelas — `evidencias.py` (processos, arvores, documentos, versoes, jobs) e `leitura_integral.py` (leituras,
fatos, docs_lidos, tabelas_lidas) — são criadas no PG com o MESMO DDL que os módulos usam (`_DDL_PG`, com os índices,
inclusive ix_fatos_sha e ix_fatos_proc) e copiadas em lotes de 5.000 com `ON CONFLICT DO NOTHING` pela chave primária
(em `fatos`, o `id`): rodar de novo não duplica. As sequências de `jobs.id`/`fatos.id` são avançadas até o MAX(id),
para a próxima inserção do app não colidir. Ao fim confere a contagem por tabela SQLite × PG; divergiu ⇒ sai 1.
O SQLite é aberto só-leitura (nada é apagado nem alterado). O DSN vem do ambiente e nunca é impresso.

Uso:
    set -a; . ~/.config/jfn/pg_evidencias.env; set +a
    .venv/bin/python tools/evidencias_para_pg.py [--sqlite data/evidencias.db] [--lote 5000] [--esquema public]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compliance_agent import evidencias as E            # noqa: E402
from compliance_agent import leitura_integral as L      # noqa: E402

TABELAS = ("processos", "arvores", "documentos", "versoes", "jobs",
           "leituras", "fatos", "docs_lidos", "tabelas_lidas")
COM_IDENTITY = ("jobs", "fatos")
LOTE = 5000


def _comandos(ddl: str) -> list[str]:
    return [c.strip() for c in ddl.split(";") if c.strip()]


def _sem_nul(linha: tuple, contador: list[int]) -> tuple:
    """O PostgreSQL recusa o caractere NUL em TEXT; o SQLite aceita. Tira o NUL e CONTA (relatado no fim)."""
    if not any(isinstance(v, str) and "\x00" in v for v in linha):
        return linha
    contador[0] += 1
    return tuple(v.replace("\x00", "") if isinstance(v, str) else v for v in linha)


def copiar(sq: sqlite3.Connection, pg, lote: int = LOTE, saida=sys.stdout) -> dict:
    """Cria as tabelas (se faltarem) e copia o que faltar. Devolve {tabela: {"sqlite", "pg", "inseridas"}}."""
    with pg.transaction():
        for c in _comandos(E._DDL_PG) + _comandos(L._DDL_PG):
            pg.execute(c)
    r: dict = {}
    for t in TABELAS:
        cols = [x[1] for x in sq.execute(f"PRAGMA table_info({t})")]
        if not cols:                                               # tabela ausente no SQLite: nada a copiar
            r[t] = {"sqlite": 0, "pg": pg.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], "inseridas": 0}
            continue
        lista = ", ".join(cols)
        ins = f"INSERT INTO {t}({lista}) VALUES({', '.join(['%s'] * len(cols))}) ON CONFLICT DO NOTHING"
        cur_sq = sq.execute(f"SELECT {lista} FROM {t} ORDER BY rowid")
        inseridas, lidas, nul = 0, 0, [0]
        while True:
            linhas = cur_sq.fetchmany(lote)
            if not linhas:
                break
            linhas = [_sem_nul(x, nul) for x in linhas]
            antes = pg.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            with pg.transaction():
                pg.cursor().executemany(ins, linhas)
            inseridas += pg.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] - antes
            lidas += len(linhas)
            print(f"{t}: {lidas} lidas, {inseridas} novas", file=saida, flush=True)
        if t in COM_IDENTITY:
            pg.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                       f"GREATEST((SELECT COALESCE(MAX(id), 0) FROM {t}), 1))")
        r[t] = {"sqlite": sq.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0],
                "pg": pg.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0], "inseridas": inseridas}
        if nul[0]:
            r[t]["linhas_com_nul_removido"] = nul[0]
    return r


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Copia data/evidencias.db para o PostgreSQL (idempotente)")
    ap.add_argument("--sqlite", default=str(E.DB), help="SQLite de origem (aberto só-leitura)")
    ap.add_argument("--lote", type=int, default=LOTE)
    ap.add_argument("--esquema", default="", help="esquema de destino (padrão: o search_path do banco)")
    a = ap.parse_args(argv)
    dsn = os.environ.get(E.ENV_DSN, "")
    if not dsn.startswith(("postgresql://", "postgres://")):
        print(f"{E.ENV_DSN} ausente no ambiente", file=sys.stderr)
        return 2
    if not Path(a.sqlite).is_file():
        print(f"SQLite não encontrado: {a.sqlite}", file=sys.stderr)
        return 2
    import psycopg
    from psycopg import sql
    sq = sqlite3.connect(f"file:{Path(a.sqlite).resolve()}?mode=ro", uri=True, timeout=60)
    pg = psycopg.connect(dsn, autocommit=True)
    try:
        if a.esquema:
            pg.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(a.esquema)))
        r = copiar(sq, pg, a.lote)
    finally:
        pg.close()
        sq.close()
    print(f"\n{'tabela':<15}{'sqlite':>12}{'pg':>12}{'novas':>12}")
    divergentes = []
    for t, x in r.items():
        marca = "" if x["sqlite"] == x["pg"] else "   ← DIVERGE"
        extra = f"   ({x['linhas_com_nul_removido']} com NUL removido)" if x.get("linhas_com_nul_removido") else ""
        print(f"{t:<15}{x['sqlite']:>12,}{x['pg']:>12,}{x['inseridas']:>12,}{marca}{extra}")
        if marca:
            divergentes.append(t)
    if divergentes:
        print(f"\nCONTAGEM DIVERGE em: {', '.join(divergentes)}", file=sys.stderr)
        return 1
    print("\nOK: contagens iguais nas 9 tabelas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
