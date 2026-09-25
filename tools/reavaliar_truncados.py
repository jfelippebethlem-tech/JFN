#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reavalia os processos cujo manifesto passou a declarar captura truncada.

POR QUE ISTO EXISTE, e por que é passagem única e não rotina. Em 2026-08-07 o arquivador passou a
gravar `docs_na_arvore` no manifesto e o gate de captura passou a obedecer ao FATO em vez da
heurística do número 40. O conserto vale para tudo o que for arquivado daí em diante — mas os
2.163 manifestos já escritos continuavam com veredito antigo no banco, calculado quando o motor
não sabia que estava lendo 4% do processo.

O sweep de 360 reavalia 120 processos a cada quatro horas, pelos maiores primeiro: alcançaria o
acervo em três dias, e nesse meio-tempo a fila do fiscal mostraria faixa de risco apoiada em
captura truncada. Esta ferramenta ataca exatamente os afetados, na ordem do BURACO MAIOR.

Ela cede a vez como todo o resto da casa: `load >= 4` interrompe. A gravação é por processo (curta),
para não segurar transação longa no `compliance.db`, que trava as rotas de leitura do painel.

    python -m tools.reavaliar_truncados            # relatório
    python -m tools.reavaliar_truncados --aplicar
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO = RAIZ / "data" / "sei_arquivo"
DB = RAIZ / "data" / "compliance.db"
LIMITE_LOAD = 4.0


def afetados() -> list[dict]:
    """Processos com veredito no banco cujo manifesto agora prova captura truncada."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        linhas = con.execute(
            "SELECT numero_sei, faixa FROM processo_avaliacao").fetchall()
    finally:
        con.close()
    fora = []
    for numero, faixa in linhas:
        slug = re.sub(r"\D", "_", str(numero).replace("SEI-", ""))
        man = ARQUIVO / slug / "manifest.json"
        if not man.is_file():
            continue
        try:
            j = json.loads(man.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        arv, n = j.get("docs_na_arvore"), len(j.get("docs") or [])
        if isinstance(arv, int) and arv > n and faixa != "NAO_AVALIAVEL":
            fora.append({"numero": numero, "faixa": faixa, "docs": n, "arvore": arv,
                         "faltam": arv - n})
    fora.sort(key=lambda x: -x["faltam"])
    return fora


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--max", type=int, default=0)
    a = ap.parse_args()
    fila = afetados()
    if a.max:
        fila = fila[:a.max]
    print(f"processos com veredito apoiado em captura truncada: {len(fila):,}")
    for x in fila[:5]:
        print(f"   {x['numero']:26s} {x['faixa']:14s} {x['docs']:4d}/{x['arvore']:4d} "
              f"faltam {x['faltam']}")
    if not a.aplicar:
        print("\n(SIMULAÇÃO — use --aplicar)")
        return 0

    from compliance_agent import processo_360

    feitos = erros = 0
    mudaram = 0
    t0 = time.time()
    for i, x in enumerate(fila, 1):
        if os.getloadavg()[0] >= LIMITE_LOAD:
            print(f"load {os.getloadavg()[0]:.1f} — cedendo a vez em {i-1}/{len(fila)}", flush=True)
            break
        try:
            out = processo_360.avaliar(x["numero"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            erros += 1
            print(f"   erro em {x['numero']}: {exc}", flush=True)
            continue
        if processo_360.gravar(out):
            feitos += 1
            if out.get("faixa") != x["faixa"]:
                mudaram += 1
        if feitos % 50 == 0 and feitos:
            print(f"   {feitos}/{len(fila)} reavaliados ({time.time()-t0:.0f}s) — "
                  f"{mudaram} mudaram de faixa", flush=True)
    print(f"\nreavaliados {feitos:,} · mudaram de faixa {mudaram:,} · erros {erros}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
