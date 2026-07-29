#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compara a releitura com o baseline congelado ANTES dela — antes×depois, sem autoengano.

    .venv/bin/python tools/comparar_releitura.py [--md ARQ]

O baseline (`data/releitura_baseline.json`) foi gravado antes de qualquer releitura, com o
estado de cada um dos 22 alvos: bytes do dossiê, citações, documentos citados e indícios. Sem
congelar o "antes", a comparação vira memória — e memória de quem torce pelo resultado.

Só entram na conta os processos cujo dossiê foi REALMENTE refeito (o antigo vai para
`output/dossies/_substituidos/`). Contar como "melhorado" um processo que a fila não alcançou
seria o mesmo erro que esta sessão corrigiu no reindiciador: acreditar no próprio relatório em
vez de olhar o produto.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parent.parent
BASELINE = RAIZ / "data" / "releitura_baseline.json"
DOSSIES = RAIZ / "output" / "dossies"
SUBSTITUIDOS = DOSSIES / "_substituidos"
NOTAS = pathlib.Path.home() / "vault" / "processos"


def _estado(pasta: str) -> dict:
    d = DOSSIES / f"{pasta}.md"
    t = d.read_text(encoding="utf-8", errors="ignore") if d.exists() else ""
    n = NOTAS / f"{pasta}.md"
    tn = n.read_text(encoding="utf-8", errors="ignore") if n.exists() else ""
    ind = re.search(r"^indicios:\s*(\d+)", tn, re.MULTILINE)
    # A citação NÃO tem formato único: o dossiê antigo escrevia `[doc 010]`, e o novo escreve
    # `[doc 010_anexo_edital_e_anexos_85050002.txt, p. 2]` — mais preciso, não menos. Medir só
    # `\[doc \d+\]` fez a releitura de 420001_003312_2024 parecer ter caído de 27 citações para
    # ZERO, quando o dossiê havia CRESCIDO de 9,9 KB para 23,3 KB. A régua media o formato.
    return {"bytes": len(t),
            "citacoes": len(re.findall(r"\[doc [^\]]+\]", t)),
            "docs_citados": len({m.split(",")[0].split("_")[0].strip()
                                 for m in re.findall(r"\[doc ([^\]]+)\]", t)}),
            "indicios": int(ind.group(1)) if ind else None,
            "lote_perdido": bool(re.search(r"lote \d+ não pôde ser lido", t))}


def comparar() -> dict:
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    refeitos = {p.name.split(".")[0] for p in SUBSTITUIDOS.glob("*.md")} if SUBSTITUIDOS.exists() else set()
    linhas, pendentes = [], []
    for pasta, antes in base.items():
        if pasta not in refeitos:
            pendentes.append(pasta)
            continue
        linhas.append({"pasta": pasta, "pago": antes.get("pago", 0.0),
                       "motivo": antes.get("motivo", ""), "antes": antes, "depois": _estado(pasta)})
    linhas.sort(key=lambda x: -x["pago"])
    return {"comparados": linhas, "pendentes": pendentes, "total_alvos": len(base)}


def _moeda(v) -> str:
    return f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def imprimir(r: dict) -> None:
    c = r["comparados"]
    print(f"alvos: {r['total_alvos']} · relidos de fato: {len(c)} · ainda na fila: {len(r['pendentes'])}\n")
    if not c:
        print("(nenhum dossiê refeito ainda — nada a comparar, e isso não é 'sem melhora')")
        return
    print(f"{'processo':24s} {'citações':>18s} {'docs citados':>16s} {'indícios':>14s}")
    for x in c:
        a, d = x["antes"], x["depois"]
        print(f"{x['pasta']:24s} {a['citacoes']:7d} → {d['citacoes']:6d} "
              f"{a['docs_citados']:7d} → {d['docs_citados']:6d} "
              f"{str(a['indicios']):>6s} → {str(d['indicios']):>5s}")
    ca, cd = sum(x["antes"]["citacoes"] for x in c), sum(x["depois"]["citacoes"] for x in c)
    ia = sum((x["antes"]["indicios"] or 0) for x in c)
    idp = sum((x["depois"]["indicios"] or 0) for x in c)
    perdidos_antes = sum(1 for x in c if x["antes"].get("lote_perdido"))
    perdidos_depois = sum(1 for x in c if x["depois"]["lote_perdido"])
    print(f"\ncitações  {ca} → {cd}" + (f"  ({cd/ca:.1f}×)" if ca else ""))
    print(f"indícios  {ia} → {idp}")
    print(f"dossiês com lote perdido  {perdidos_antes} → {perdidos_depois}")
    print(f"valor pago sob releitura: R$ {_moeda(sum(x['pago'] for x in c))}")
    print("\nIndício é hipótese a verificar. Mais citação não é 'mais irregularidade': é mais "
          "processo efetivamente lido.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--md", help="grava o comparativo em markdown")
    a = ap.parse_args()
    r = comparar()
    imprimir(r)
    if a.md:
        linhas = ["# Releitura dos alvos — antes × depois\n\n",
                  f"Alvos: {r['total_alvos']} · relidos: {len(r['comparados'])} · "
                  f"na fila: {len(r['pendentes'])}\n\n",
                  "| processo | pago | citações | docs citados | indícios | motivo da releitura |\n",
                  "|---|---:|---:|---:|---:|---|\n"]
        for x in r["comparados"]:
            a_, d_ = x["antes"], x["depois"]
            linhas.append(f"| {x['pasta']} | R$ {_moeda(x['pago'])} | {a_['citacoes']} → {d_['citacoes']} | "
                          f"{a_['docs_citados']} → {d_['docs_citados']} | {a_['indicios']} → {d_['indicios']} | "
                          f"{x['motivo']} |\n")
        pathlib.Path(a.md).write_text("".join(linhas), encoding="utf-8")
        print(f"\nmarkdown: {a.md}")
    return 0


if __name__ == "__main__":   # importar este módulo NÃO pode disparar o trabalho
    raise SystemExit(main())
