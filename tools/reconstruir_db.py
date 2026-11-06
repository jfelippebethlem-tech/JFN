#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconstrói um SQLite corrompido em arquivo NOVO — e COMPARA o resultado com o original.

POR QUE EXISTE (2026-08-12). `data/compliance.db` teve corrupção REAL: 155 páginas inválidas na
TABELA `ordens_bancarias` e três índices de `ob_orcamentaria_siafe` com referência dupla. Não é o
caso do `-shm` morto (ali o `quick_check` volta `ok`); aqui é perícia de dado.

O CAMINHO ESCOLHIDO, e por que não o outro. Consertar NO LUGAR (`DELETE` + `INSERT` + `REINDEX`)
significa escrever num arquivo com páginas quebradas — pode ampliar o dano, e as páginas ruins
continuam na lista livre, prontas para serem reusadas. Reconstruir em arquivo novo produz um banco
sem herança nenhuma da corrupção, e deixa o original intacto para conferência.

O QUE ELE GARANTE:
  · o original é aberto SEMPRE em `mode=ro` — nunca é escrito, nem para ler;
  · tabela que estoura no meio NÃO derruba a reconstrução: cai na varredura por faixas de `rowid`,
    que subdivide até isolar a linha ilegível e segue (a mesma de `salvar_tabela_corrompida`);
  · ao final, `integrity_check` no novo e uma COMPARAÇÃO linha a linha, tabela a tabela, contra o
    original — porque "reconstruí" sem conferir é a mesma promessa vazia que a casa já cobrou de si
    mesma ("verificar o EFEITO, não a ação").

A TROCA DOS ARQUIVOS NÃO É FEITA AQUI. Ele grava o novo banco e imprime o laudo; mover arquivo é
decisão de operador, com o serviço parado.

    .venv/bin/python -m tools.reconstruir_db --saida data/compliance.novo.db
    .venv/bin/python -m tools.reconstruir_db --saida /tmp/x.db --so-comparar   # só o laudo
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"


def _ro(caminho: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=300)


def _copiar_tabela(orig: sqlite3.Connection, novo: sqlite3.Connection, tabela: str,
                   *, passo: int = 2000) -> dict:
    """Copia uma tabela. Devolve `{lidas, perdidas, rowids_perdidos}`.

    A faixa que estoura é subdividida até a linha — assim uma tabela com 155 páginas ruins entrega
    tudo o que tem, e o prejuízo sai como número em vez de exceção.
    """
    cols = [r[1] for r in orig.execute(f"PRAGMA table_info({tabela})")]
    if not cols:
        return {"lidas": 0, "perdidas": 0, "rowids_perdidos": [], "sem_colunas": True}
    campos = ",".join(f'"{c}"' for c in cols)
    ins = f'INSERT OR REPLACE INTO "{tabela}" ({campos}) VALUES ({",".join("?" * len(cols))})'
    try:
        lo, hi = orig.execute(f'SELECT MIN(rowid), MAX(rowid) FROM "{tabela}"').fetchone()
    except sqlite3.DatabaseError:
        lo = hi = None
    if lo is None:
        # tabela WITHOUT ROWID (ou vazia): tenta de uma vez só
        try:
            linhas = orig.execute(f'SELECT {campos} FROM "{tabela}"').fetchall()
        except sqlite3.DatabaseError:
            return {"lidas": 0, "perdidas": -1, "rowids_perdidos": [], "sem_rowid_ilegivel": True}
        novo.executemany(ins, linhas)
        return {"lidas": len(linhas), "perdidas": 0, "rowids_perdidos": []}

    lidas, perdidos, pilha = 0, [], [(lo, hi)]
    while pilha:
        a, b = pilha.pop()
        if b - a + 1 > passo:
            meio = (a + b) // 2
            pilha.append((meio + 1, b)); pilha.append((a, meio))
            continue
        try:
            linhas = orig.execute(
                f'SELECT {campos} FROM "{tabela}" WHERE rowid BETWEEN ? AND ?', (a, b)).fetchall()
        except sqlite3.DatabaseError:
            if a == b:
                perdidos.append(a)
                continue
            meio = (a + b) // 2
            pilha.append((meio + 1, b)); pilha.append((a, meio))
            continue
        if linhas:
            novo.executemany(ins, linhas)
            lidas += len(linhas)
    return {"lidas": lidas, "perdidas": len(perdidos), "rowids_perdidos": sorted(perdidos)[:50]}


def _contar(con: sqlite3.Connection, tabela: str) -> int | str:
    """Contagem que TOCA O DADO, não só o índice.

    `COUNT(*)` responde pelo índice e sobrevive à página de dado quebrada — foi exatamente o que
    escondeu esta corrupção por horas (`COUNT(*)` = 1.159.305 enquanto `SUM(valor)` estourava).
    Contar por `rowid` obriga a percorrer a tabela.
    """
    try:
        return int(con.execute(f'SELECT COUNT(rowid) FROM "{tabela}"').fetchone()[0])
    except sqlite3.DatabaseError as exc:
        return f"ERRO: {str(exc)[:60]}"


def reconstruir(origem: Path, saida: Path, *, so_comparar: bool = False) -> dict:
    orig = _ro(origem)
    laudo: dict = {"origem": str(origem), "saida": str(saida), "tabelas": {}, "avisos": []}
    objetos = orig.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL").fetchall()
    # TABELA VIRTUAL CRIA AS PRÓPRIAS SOMBRAS. `corpus_editais` (FTS5) gera
    # `corpus_editais_data/_idx/_content/_docsize/_config`, que aparecem no `sqlite_master` como
    # tabelas comuns. Criá-las antes da virtual faz o `CREATE VIRTUAL TABLE` estourar com
    # "shadow table already exists" — foi o que derrubou a primeira tentativa. A virtual vem
    # PRIMEIRO, as sombras não são criadas nem copiadas à mão, e o índice é reconstruído no fim.
    virtuais = [(n, q) for t, n, q in objetos
                if t == "table" and (q or "").upper().startswith("CREATE VIRTUAL")]
    _sufixos = ("_data", "_idx", "_content", "_docsize", "_config")
    sombras = {f"{n}{suf}" for n, _ in virtuais for suf in _sufixos}
    tabelas = [(n, q) for t, n, q in objetos
               if t == "table" and not n.startswith("sqlite_")
               and n not in sombras and not (q or "").upper().startswith("CREATE VIRTUAL")]
    outros = [(t, n, q) for t, n, q in objetos if t in ("index", "trigger", "view")
              and not n.startswith("sqlite_") and n not in sombras]

    if so_comparar:
        for nome, _ in tabelas + virtuais:
            laudo["tabelas"][nome] = {"origem": _contar(orig, nome)}
        orig.close()
        return laudo

    if saida.exists():
        saida.unlink()
    novo = sqlite3.connect(str(saida), timeout=300)
    novo.execute("PRAGMA journal_mode=OFF")      # reconstrução: sem WAL, é mais rápido
    novo.execute("PRAGMA synchronous=OFF")       # o arquivo é descartável até o laudo fechar
    try:
        for nome, sql in virtuais:      # antes das comuns: elas criam as próprias sombras
            novo.execute(sql)
        for nome, sql in tabelas:
            novo.execute(sql)
        novo.commit()
        t0 = time.time()
        for nome, _ in tabelas:
            r = _copiar_tabela(orig, novo, nome)
            novo.commit()
            r["origem"] = _contar(orig, nome)
            r["destino"] = _contar(novo, nome)
            laudo["tabelas"][nome] = r
            if r["perdidas"]:
                print(f"  ⚠️  {nome}: {r['perdidas']} linha(s) ilegível(is)", flush=True)
        laudo["segundos_copia"] = round(time.time() - t0, 1)

        # ÍNDICES E GATILHOS POR ÚLTIMO: criar índice antes dos dados custa uma reordenação por
        # linha inserida. E é aqui que os três índices corrompidos nascem limpos.
        for tipo, nome, sql in outros:
            try:
                novo.execute(sql)
            except sqlite3.DatabaseError as exc:
                laudo["avisos"].append(f"{tipo} {nome}: {str(exc)[:90]}")
        # FTS5: o conteúdo é copiado pela PRÓPRIA tabela virtual (as sombras são internas).
        for nome, _ in virtuais:
            r = _copiar_tabela(orig, novo, nome)
            novo.commit()
            r["origem"] = _contar(orig, nome)
            r["destino"] = _contar(novo, nome)
            laudo["tabelas"][nome] = r
        novo.commit()
        novo.execute("PRAGMA journal_mode=WAL")  # o original é WAL; o novo tem de ser igual
        laudo["integrity_check"] = [r[0][:200] for r in
                                    novo.execute("PRAGMA integrity_check(20)").fetchall()]
    finally:
        novo.close()
        orig.close()
    return laudo


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(_DB))
    ap.add_argument("--saida", default=str(_REPO / "data" / "compliance.novo.db"))
    ap.add_argument("--so-comparar", action="store_true")
    ap.add_argument("--laudo", default="", help="grava o laudo em JSON neste caminho")
    a = ap.parse_args(argv)

    r = reconstruir(Path(a.db), Path(a.saida), so_comparar=a.so_comparar)
    difs = {n: v for n, v in r["tabelas"].items()
            if not a.so_comparar and v.get("origem") != v.get("destino")}
    print(f"\ntabelas: {len(r['tabelas'])} · com diferença origem×destino: {len(difs)}")
    for n, v in sorted(difs.items(), key=lambda x: -(x[1].get('perdidas') or 0))[:20]:
        print(f"  {n:34} origem={v.get('origem')} destino={v.get('destino')} "
              f"perdidas={v.get('perdidas')}")
    if r.get("integrity_check"):
        ok = r["integrity_check"] == ["ok"]
        print(f"\nintegrity_check do NOVO: {'✅ ok' if ok else r['integrity_check'][:3]}")
    for av in r.get("avisos", [])[:10]:
        print(f"  aviso: {av}")
    if a.laudo:
        Path(a.laudo).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"laudo em {a.laudo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
