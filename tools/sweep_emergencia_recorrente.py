#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Varredura de EMERGÊNCIA RECORRENTE — o irmão que faltava do sweep de fracionamento.

    .venv/bin/python tools/sweep_emergencia_recorrente.py [--minimo 5] [--top 30] [--md ARQ]

O sweep de fracionamento mede dispensa por VALOR (art. 75, II). Esta mede o outro caminho de
fuga à licitação, que na base do Estado é muito maior: a dispensa EMERGENCIAL (art. 75, VIII),
cujo teto é o próprio valor da urgência alegada.

Medido em 2026-07-28: **1.638 contratações emergenciais, R$ 1.963.745.047,92**.

HONESTIDADE: emergência é legal e necessária — um hospital sem insumo depende dela. O indício
é a RECORRÊNCIA, medida e não presumida, e o julgamento fino de cada caso é do card P5 sobre o
processo. Aqui é a triagem que diz onde olhar primeiro.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from compliance_agent.fracionamento_emergencia import agrupar_emergencias  # noqa: E402

DB = os.environ.get("JFN_DB", "data/compliance.db")


def _moeda(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def carregar(con: sqlite3.Connection):
    return con.execute(
        "SELECT unidade, ano_processo, fornecedor, valor, objeto FROM compras_diretas_tcerj"
    ).fetchall()


def relatorio_md(grupos: list[dict], minimo: int) -> str:
    linhas = [
        "# Emergência recorrente — triagem (art. 75, VIII, Lei 14.133/2021)\n",
        f"\n> {grupos[0]['ressalva'] if grupos else 'sem grupos'}\n",
        f"\n> Critério: {minimo}+ contratações emergenciais na mesma unidade e exercício.\n",
        "\n| unidade | exercício | contratações | soma | fornecedor dominante | concentração |\n",
        "|---|---:|---:|---:|---|---:|\n",
    ]
    for g in grupos:
        linhas.append(
            f"| {g['unidade'][:44]} | {g['exercicio']} | {g['n']} | R$ {_moeda(g['total'])} | "
            f"{g['fornecedor_dominante'][:32]} | {g['concentracao_dominante']:.0%} |\n")
    total = sum(g["total"] for g in grupos)
    linhas.append(f"\n**{len(grupos)} grupo(s) · R$ {_moeda(total)} em contratação emergencial.**\n")
    return "".join(linhas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--minimo", type=int, default=5,
                    help="emergências no mesmo exercício para virar indício (padrão 5)")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--md", help="grava o relatório em markdown neste caminho")
    a = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    try:
        grupos = agrupar_emergencias(carregar(con), minimo=a.minimo)
    finally:
        con.close()

    print(f"grupos (unidade × exercício) com {a.minimo}+ contratações emergenciais: {len(grupos)}")
    print(f"soma envolvida: R$ {_moeda(sum(g['total'] for g in grupos))}\n")
    for g in grupos[:a.top]:
        print(f"  {g['unidade'][:44]:46s} {g['exercicio']} · {g['n']:4d} emerg. · "
              f"R$ {_moeda(g['total']):>16s} · {g['concentracao_dominante']:.0%} em "
              f"{g['fornecedor_dominante'][:28]}")
    if a.md:
        pathlib.Path(a.md).write_text(relatorio_md(grupos[:a.top], a.minimo), encoding="utf-8")
        print(f"\nmarkdown: {a.md}")
    print(f"\n{grupos[0]['ressalva'] if grupos else ''}")
    return 0


if __name__ == "__main__":   # importar este módulo NÃO pode disparar o trabalho
    sys.exit(main())
