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

from compliance_agent.fracionamento_emergencia import (agrupar_emergencias,  # noqa: E402
                                                       sinais_do_dominante)

DB = os.environ.get("JFN_DB", "data/compliance.db")


def _moeda(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def carregar(con: sqlite3.Connection):
    """Uma linha por PROCESSO — que é a unidade da contratação. Nunca por item.

    `compras_diretas_tcerj` tem uma linha por ITEM, e o campo `valor` repete o **total do
    processo** em cada uma. Medido em 2026-08-11: dos 1.486 processos com 2+ linhas, **1.485 têm
    `valor` idêntico em todas**; somar linha a linha infla o acervo inteiro em **2,30×**
    (R$ 39,65 bi contra R$ 17,20 bi). No DETRAN/2025 isso virava "6 contratações emergenciais,
    R$ 148,8 mi" onde há UM processo de R$ 24,8 mi, com seis itens de vigilância
    (armada/desarmada, diurno/noturno, supervisor) — a soma de `quantidade × valor_unitario`
    vezes os 6 meses de vigência dá exatamente o `valor` repetido.

    O sweep IRMÃO já fazia assim (`sweep_fracionamento_tcerj`: `MAX(valor) ... GROUP BY processo`,
    com o comentário "1 linha por processo"). A régua existia numa cópia só — e é a mesma família
    do fracionamento que esteve 26× inflado: contar LINHA onde o fenômeno é PROCESSO.

    `enquadramento_legal` entra como 6º campo porque o OBJETO não prova a emergência: objeto e
    dispositivo só coincidem em 613 de 1.504 dispensas do art. 75, VIII — 891 delas (R$ 2,60 bi)
    diziam "PEITO DE FRANGO" e ficavam fora da triagem.
    """
    return con.execute(
        "SELECT unidade, ano_processo, fornecedor, MAX(valor), MIN(objeto), "
        "       MIN(enquadramento_legal) "
        "FROM compras_diretas_tcerj "
        "GROUP BY processo, unidade, ano_processo, fornecedor"
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
    ap.add_argument("--cadastro", action="store_true",
                    help="cruza o fornecedor dominante com o cadastro (sinais e LACUNAS)")
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
    if a.cadastro:
        # SINAL é o que sabemos da empresa; LACUNA é o que nós não temos. Ausência no cadastro
        # não diz nada sobre o contratado — diz que o enriquecimento não chegou nele.
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
        try:
            print()
            for g in grupos[:a.top]:
                nome = g["fornecedor_dominante"]
                row = con.execute(
                    "SELECT situacao, data_abertura FROM empresas WHERE UPPER(razao_social) LIKE ? LIMIT 1",
                    (f"%{nome[:20].upper()}%",)).fetchone()
                cad = {"situacao": row[0], "data_abertura": row[1]} if row else None
                d = sinais_do_dominante(g, cad)
                if not (d["sinais"] or d["lacunas"]):
                    continue
                print(f"  {g['unidade'][:40]} {g['exercicio']}")
                for x in d["sinais"]:
                    print(f"     ⚠ {x}")
                for x in d["lacunas"]:
                    print(f"     ◌ {x}")
        finally:
            con.close()

    if a.md:
        pathlib.Path(a.md).write_text(relatorio_md(grupos[:a.top], a.minimo), encoding="utf-8")
        print(f"\nmarkdown: {a.md}")
    print(f"\n{grupos[0]['ressalva'] if grupos else ''}")
    return 0


if __name__ == "__main__":   # importar este módulo NÃO pode disparar o trabalho
    sys.exit(main())
