#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Confere no PNCP (fonte primária) cada indício de sobrepreço das abas Estado e Prefeitura.

Uso:  nice .venv/bin/python -m tools.verificar_precos_pncp [--max 300] [--pausa 1.0] [--refazer]

Para cada achado da aba Sobrepreço (que é também a base da "economia potencial"), consulta
o item e o resultado no PNCP e grava VERIFICADO / DIVERGENTE em data/verificacao_precos.db
(SQLite próprio — não escreve no compliance.db). Também grava se a contratação é ATA DE
REGISTRO DE PREÇOS (`srp`): quantidade de ata é estimativa e não entra na economia.

Carga: 3 requisições por achado novo, com pausa — bounded por --max. Falha de rede deixa o
item PENDENTE (nunca vira verificado).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compliance_agent import verificacao_pncp as V  # noqa: E402
from compliance_agent.cruzamentos_intel import sobrepreco  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=None)
    ap.add_argument("--max", type=int, default=300, help="máximo de achados a conferir")
    ap.add_argument("--pausa", type=float, default=1.0)
    ap.add_argument("--refazer", action="store_true")
    a = ap.parse_args()
    linhas = []
    for esf in ("estado", "prefeitura"):
        d = sobrepreco(db_path=a.db, limite=100_000, esfera=esf)
        for x in d["achados"]:
            if x.get("item_n") is None:
                continue
            linhas.append({"certame": x["certame"], "item": x["item_n"],
                           "fornecedor_cnpj": x["fornecedor_cnpj"], "descricao": x["item"],
                           "unidade": x["unidade_medida"], "quantidade": x["quantidade"],
                           "valor_unitario": x["preco"],
                           "_peso": x.get("excesso_total_est") or 0})
        print(f"{esf}: {d['n']} achados")
    linhas.sort(key=lambda r: -r["_peso"])      # o que mais pesa na conta primeiro
    print(f"conferindo até {a.max} de {len(linhas)} no PNCP…")
    r = V.verificar(a.db, linhas[:a.max], pausa=a.pausa, refazer=a.refazer)
    print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
