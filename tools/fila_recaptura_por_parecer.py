# -*- coding: utf-8 -*-
"""Materializa, na fila de captura, os processos cujo PARECER prova que a coleta está incompleta.

Sem isto, a conferência do `sei/conferencia_captura` seria relatório: apareceria no PDF do 360 e
morreria ali. Aqui ela vira trabalho — o processo entra em `sei_fila_captura` com o motivo e a
lista de documentos que faltam, e o sweep o recaptura.

A fila é por PROCESSO (é assim que o sweep trabalha), mas o motivo carrega os números dos
documentos: quem for conferir à mão sabe exatamente o que procurar.

Medido no acervo em 2026-08-03: 2.175 processos varridos, 370 com documento citado pelo parecer e
ausente da captura. Dry-run por padrão — `--gravar` é explícito.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from compliance_agent import processo_360 as P360  # noqa: E402
from compliance_agent.sei import conferencia_captura as CC  # noqa: E402
from compliance_agent.sei import manifesto_norm  # noqa: E402

DB = RAIZ / "data" / "compliance.db"
_DDL = """
CREATE TABLE IF NOT EXISTS sei_fila_captura (
    numero_sei TEXT PRIMARY KEY, sei_norm TEXT, motivo TEXT,
    total_pago REAL, n_docs INTEGER, visto_em TEXT
);
"""


def _norm(numero: str) -> str:
    return re.sub(r"\D", "", numero or "")


def varrer(limite: int, segundos: int) -> list[dict]:
    """Processos com documento citado pelo parecer e ausente da nossa captura."""
    t0 = time.time()
    saida: list[dict] = []
    for man in sorted((RAIZ / "data" / "sei_arquivo").glob("*/manifest.json")):
        if len(saida) >= limite or (time.time() - t0) > segundos:
            break
        pasta = man.parent
        try:
            m = manifesto_norm.normalizar(
                {**json.loads(man.read_text(encoding="utf-8")), "_pasta": str(pasta)})
            docs = [{"ref": d.get("titulo", ""), "tipo": d.get("tipo", ""),
                     "texto": P360._texto_de(pasta, d, teto=400_000)} for d in m["docs"]]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        r = CC.conferir(docs)
        if not r.get("achado"):
            continue
        saida.append({"numero_sei": str(m.get("processo") or pasta.name),
                      "ausentes": r["ausentes"], "n_citados": r["n_citados"],
                      "n_docs": len(docs)})
    return saida


def gravar(itens: list[dict]) -> int:
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        con.executescript(_DDL)
        agora = con.execute("select datetime('now')").fetchone()[0]
        n = 0
        for it in itens:
            motivo = (f"parecer cita {it['n_citados']} documentos e "
                      f"{len(it['ausentes'])} faltam na captura: "
                      + ", ".join(it["ausentes"][:20]))
            # `INSERT OR REPLACE` de propósito: o motivo é o estado ATUAL da lacuna, e uma
            # recaptura parcial precisa reescrevê-lo — fila com motivo velho manda o fiscal
            # procurar documento que já chegou.
            con.execute(
                "insert or replace into sei_fila_captura"
                " (numero_sei, sei_norm, motivo, n_docs, visto_em) values (?,?,?,?,?)",
                (it["numero_sei"], _norm(it["numero_sei"]), motivo, it["n_docs"], agora))
            n += 1
        con.commit()
        return n
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limite", type=int, default=3000)
    ap.add_argument("--segundos", type=int, default=1200)
    ap.add_argument("--gravar", action="store_true", help="materializa em sei_fila_captura")
    a = ap.parse_args()

    itens = varrer(a.limite, a.segundos)
    faltando = sum(len(i["ausentes"]) for i in itens)
    print(f"processos com lacuna provada pelo parecer: {len(itens)} · "
          f"documentos a capturar: {faltando}")
    for it in itens[:10]:
        print(f"  {it['numero_sei']}: faltam {len(it['ausentes'])} de {it['n_citados']} "
              f"({', '.join(it['ausentes'][:6])})")
    if len(itens) > 10:
        print(f"  … e mais {len(itens) - 10} processos")
    if a.gravar:
        print(f"gravados na fila: {gravar(itens)}")
    else:
        print("(dry-run — use --gravar para materializar)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
