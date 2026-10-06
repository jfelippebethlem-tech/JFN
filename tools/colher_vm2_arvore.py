#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Traz da VM-2 as linhas de `sei_arvore` que a VM-1 não tem — o denominador da captura.

POR QUE ISTO IMPORTA, e não é detalhe de sincronização. `sei_arvore.n_docs` é quantos documentos o
processo TEM; o arquivo diz quantos foram LIDOS. Sem o primeiro número, "16 documentos lidos" é
indistinguível de "processo de 16 documentos lido inteiro" — e ler o segundo como o primeiro é a
família 22 do catálogo (*o gate mede o que li, não o que existe*), que já sustentou 14 dos 28
EXTREMO com base em captura truncada.

Medido em 2026-08-07, logo depois da primeira colheita de cache: dos 63 processos trazidos da VM-2,
**44 não tinham árvore conhecida na VM-1**. A VM-2 conhecia 3.998 árvores e nenhuma atravessava.

Só INSERE o que falta: nunca sobrescreve linha local, porque a árvore local pode ser mais recente
(a VM-1 é quem roda o `sei_arvore_build` sobre o acervo completo).

    python -m tools.colher_vm2_arvore            # relatório
    python -m tools.colher_vm2_arvore --aplicar
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"

_REMOTO = r"""cd ~/JFN && .venv/bin/python -c "
import sqlite3, json
c = sqlite3.connect('file:data/compliance.db?mode=ro', uri=True)
c.row_factory = sqlite3.Row
print(json.dumps([dict(r) for r in c.execute('SELECT * FROM sei_arvore')]))
" """


def buscar_da_vm2(timeout_s: int = 300) -> list[dict]:
    """Lê a `sei_arvore` da VM-2 por ssh. Falha vira lista vazia — a colheita não pode derrubar nada."""
    try:
        p = subprocess.run(["ssh", "-o", "ConnectTimeout=20", "-o", "BatchMode=yes", "vm2",
                            _REMOTO], capture_output=True, timeout=timeout_s)
    except (subprocess.TimeoutExpired, OSError):
        return []
    if p.returncode != 0:
        return []
    try:
        return json.loads(p.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return []


def colher(aplicar: bool = False, db: Path = _DB) -> dict:
    linhas = buscar_da_vm2()
    if not linhas:
        return {"erro": "não consegui ler a sei_arvore da VM-2 (ssh/permissão/tabela)"}
    con = sqlite3.connect(str(db), timeout=60)
    try:
        locais = {r[0] for r in con.execute("SELECT numero_sei FROM sei_arvore")}
        novas = [x for x in linhas if x.get("numero_sei") not in locais]
        if aplicar and novas:
            cols = [c[1] for c in con.execute("PRAGMA table_info(sei_arvore)")]
            ph = ",".join("?" * len(cols))
            con.executemany(
                f"INSERT OR IGNORE INTO sei_arvore ({','.join(cols)}) VALUES ({ph})",
                [tuple(x.get(c) for c in cols) for x in novas])
            con.commit()
        return {"na_vm2": len(linhas), "ja_locais": len(linhas) - len(novas),
                "novas": len(novas), "aplicado": bool(aplicar and novas)}
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args()
    for k, v in colher(a.aplicar).items():
        print(f"{k:14s} {v}")


if __name__ == "__main__":
    main()
