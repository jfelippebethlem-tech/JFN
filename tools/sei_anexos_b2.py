#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sei_anexos_b2 — migra DOSSIÊS SEI grandes p/ a nuvem (R2→B2) e grava o ponteiro em `sei_arvore.anexo_b2`.

Fase 6 do cérebro vivo: replica a política da fachada (`anexos_remotes`/`fachada_remotes`) p/ os anexos que
crescem e não convém manter só na VM. Aqui o alvo são os dossiês consolidados (`data/sei_trees/*.txt`)
ACIMA de um limiar de tamanho (default 32KB; a maioria é pequena e fica local — só os grandes migram).

Fluxo (idêntico à fachada): seleciona os dossiês grandes ainda SEM ponteiro → `anexos_remotes.subir_anexo`
(escolhe R2→B2 sob o teto) → grava a LOCALIZAÇÃO COMPLETA `remote:bucket/objeto` na coluna `anexo_b2`.
A leitura (Lex/relatório) usa `anexos_remotes.ler_anexo(loc)` no caminho EXATO. Idempotente, VM-safe
(`--limite`, load-guard), honesto (falha de upload → NÃO grava ponteiro, reentra no próximo run).

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.sei_anexos_b2 --min-kb 32 --limite 50
    PYTHONPATH=. .venv/bin/python -m tools.sei_anexos_b2 --numero SEI-330003/002534/2024 --forcar
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "compliance.db"


def _garante_coluna(con: sqlite3.Connection) -> None:
    """ALTER TABLE ADD COLUMN idempotente — ponteiro do dossiê na nuvem (remote:bucket/objeto)."""
    if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sei_arvore'").fetchone():
        return
    cols = {r[1] for r in con.execute("PRAGMA table_info(sei_arvore)")}
    if "anexo_b2" not in cols:
        con.execute("ALTER TABLE sei_arvore ADD COLUMN anexo_b2 TEXT")


def _load_ok(teto: float = 4.0) -> bool:
    try:
        return os.getloadavg()[0] < teto
    except OSError:
        return True


def _alvos(con: sqlite3.Connection, min_bytes: int, limite: int, numero: str | None,
           forcar: bool) -> list[tuple[str, str]]:
    """(numero_sei, txt_path) dos dossiês candidatos: txt local existe, tamanho ≥ min_bytes, e ainda sem
    ponteiro (salvo --forcar). Filtra por --numero se dado."""
    where = ["txt_path IS NOT NULL", "txt_path <> ''"]
    args: list = []
    if numero:
        where.append("numero_sei = ?")
        args.append(numero)
    if not forcar:
        where.append("(anexo_b2 IS NULL OR anexo_b2 = '')")
    rows = con.execute(
        f"SELECT numero_sei, txt_path FROM sei_arvore WHERE {' AND '.join(where)}", tuple(args)).fetchall()
    out: list[tuple[str, str]] = []
    for numero_sei, txt_path in rows:
        p = Path(txt_path)
        try:
            if p.exists() and p.stat().st_size >= min_bytes:
                out.append((numero_sei, txt_path))
        except OSError:
            continue
        if limite and len(out) >= limite:
            break
    return out


def migrar(min_kb: int = 32, limite: int = 0, numero: str | None = None, forcar: bool = False) -> dict:
    if not DB.exists():
        return {"erro": "compliance.db ausente"}
    if not _load_ok():
        return {"erro": "load alto — adiado (VM-safe)"}
    from compliance_agent import anexos_remotes, fachada_remotes
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    _garante_coluna(con)
    con.commit()
    alvos = _alvos(con, min_kb * 1024, limite, numero, forcar)
    if not alvos:
        con.close()
        return {"alvos": 0, "migrados": 0, "falhas": 0}
    sel = fachada_remotes.SelecionadorRemote()  # 1 rclone size por remote no run (não por arquivo)
    migrados = falhas = 0
    for numero_sei, txt_path in alvos:
        objeto = anexos_remotes.objeto_anexo("dossies", numero_sei, "txt")
        loc = anexos_remotes.subir_anexo(txt_path, objeto, sel=sel)
        if not loc:           # remotes cheios / rclone falhou → NÃO grava ponteiro (honesto, reentra depois)
            falhas += 1
            continue
        con.execute("UPDATE sei_arvore SET anexo_b2=? WHERE numero_sei=?", (loc, numero_sei))
        con.commit()
        migrados += 1
    con.close()
    return {"alvos": len(alvos), "migrados": migrados, "falhas": falhas}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-kb", type=int, default=32, help="só migra dossiês ≥ este tamanho (KB)")
    ap.add_argument("--limite", type=int, default=0, help="máx dossiês por run (0=todos os elegíveis)")
    ap.add_argument("--numero", type=str, default=None, help="migra só este processo SEI")
    ap.add_argument("--forcar", action="store_true", help="re-sobe mesmo com ponteiro já gravado")
    a = ap.parse_args()
    r = migrar(min_kb=a.min_kb, limite=a.limite, numero=a.numero, forcar=a.forcar)
    if r.get("erro"):
        print(f"[sei_anexos_b2] {r['erro']}")
        return 1
    print(f"[sei_anexos_b2] alvos={r['alvos']} · migrados={r['migrados']} · falhas={r['falhas']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
