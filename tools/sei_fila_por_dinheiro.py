#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monta a fila de captura do SEI ordenada por DINHEIRO PAGO — o que ainda não foi tocado.

Achado que originou a ferramenta (2026-07-24), medido no banco:

    22.587 processos SEI com Ordem Bancária
       311 arquivados (1,4%)
     3.433 lidos pelo sweep, ainda não arquivados
    18.843 NUNCA TOCADOS — somando R$ 2,11 BILHÕES pagos

A fila existente (`sei_integra_fila._fila_geral`) só enxerga processos que já têm `cdp_*.json` no cache,
isto é, que o sweep já leu. Os 18.843 restantes eram invisíveis para ela — e é justamente ali que está o
grosso do dinheiro. O efeito prático aparecia no dossiê: fornecedores de R$ 1,1 bilhão (obras) e R$ 972
milhões (serviços) saíam SEM o capítulo de execução, porque nenhum processo deles fora capturado.

Critério: valor total de OB do processo (§2 — OB é pagamento efetivo, não empenho). Quem recebeu mais
dinheiro público é lido primeiro. Honesto: a fila é só uma ORDEM DE LEITURA; não afirma nada sobre os
processos, e o que já está arquivado é pulado (idempotente).

Uso:
    python -m tools.sei_fila_por_dinheiro                    # relatório do gap (não escreve)
    python -m tools.sei_fila_por_dinheiro --gravar --top 500 # grava data/sei_fila_dinheiro.json
    python -m tools.sei_fila_por_dinheiro --fornecedor CNPJ  # só os processos de um fornecedor
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from compliance_agent.reporting.intel_base import moeda

RAIZ = Path(__file__).resolve().parent.parent
DB = RAIZ / "data" / "compliance.db"
CACHE = RAIZ / "data" / "sei_cache"
ARQUIVO = RAIZ / "data" / "sei_arquivo"
SAIDA = RAIZ / "data" / "sei_fila_dinheiro.json"


def _slug(numero: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in (numero or "").replace("SEI-", "")).strip("_")


def _ja_arquivado(numero: str) -> bool:
    """Arquivado = tem manifesto E algum texto com conteúdo. Manifesto sozinho pode ser captura vazia."""
    d = ARQUIVO / _slug(numero)
    if not (d / "manifest.json").exists():
        return False
    td = d / "texto"
    return td.is_dir() and any(f.stat().st_size > 200 for f in td.glob("*.txt"))


def levantar(fornecedor: str | None = None) -> dict:
    """Processos SEI com OB, separados por estado de captura e ordenados por valor pago."""
    if not DB.exists():
        return {"erro": "compliance.db ausente"}
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        sql = ("SELECT numero_sei, ROUND(SUM(valor),2) v, MAX(favorecido_nome) nome, "
               "       MAX(REPLACE(REPLACE(REPLACE(favorecido_cpf,'.',''),'/',''),'-','')) cnpj, COUNT(*) n "
               "FROM ordens_bancarias WHERE numero_sei LIKE 'SEI-%/%/20%'")
        params: list = []
        if fornecedor:
            sql += " AND REPLACE(REPLACE(REPLACE(favorecido_cpf,'.',''),'/',''),'-','') = ?"
            params.append(re.sub(r"\D", "", fornecedor))
        sql += " GROUP BY numero_sei ORDER BY v DESC"
        linhas = con.execute(sql, params).fetchall()
    finally:
        con.close()
    cdps = {f.stem.replace("cdp_", "").replace("SEI_", "") for f in CACHE.glob("cdp_*.json")}
    arquivados, lidos, faltam = [], [], []
    for numero, valor, nome, cnpj, n_ob in linhas:
        item = {"sei": numero, "score": float(valor or 0), "valor_ob": float(valor or 0),
                "forn": (nome or "").strip(), "cnpj": cnpj, "n_ob": n_ob,
                "tipo": "DINHEIRO", "flags": ["FILA_POR_VALOR_PAGO"]}
        if _ja_arquivado(numero):
            arquivados.append(item)
        elif _slug(numero) in cdps or f"SEI_{_slug(numero)}" in cdps:
            lidos.append(item)          # já lido: a fila de íntegra existente cuida
        else:
            faltam.append(item)         # nunca tocado: é este o buraco
    return {"total": len(linhas), "arquivados": arquivados, "lidos_nao_arquivados": lidos,
            "nunca_tocados": faltam,
            "dinheiro_nunca_tocado": round(sum(i["valor_ob"] for i in faltam), 2)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gravar", action="store_true", help="grava a fila em data/sei_fila_dinheiro.json")
    ap.add_argument("--top", type=int, default=500, help="quantos processos gravar (default 500)")
    ap.add_argument("--fornecedor", default="", help="restringe a um CNPJ")
    a = ap.parse_args(argv)
    r = levantar(a.fornecedor or None)
    if "erro" in r:
        print(r["erro"])
        return 1
    print(f"processos SEI com OB: {r['total']:,}")
    print(f"  arquivados (com texto): {len(r['arquivados']):,}")
    print(f"  lidos, falta arquivar:  {len(r['lidos_nao_arquivados']):,}")
    print(f"  NUNCA TOCADOS:          {len(r['nunca_tocados']):,}  "
          f"— R$ {moeda(r['dinheiro_nunca_tocado'])} pagos")
    fila = (r["nunca_tocados"] + r["lidos_nao_arquivados"])[:a.top]
    print(f"\ntop {min(10, len(fila))} da fila proposta (por valor pago):")
    for i in fila[:10]:
        print(f"  R$ {i['valor_ob']:>14,.2f}  {i['sei']:28s} {i['forn'][:36]}")
    if a.gravar:
        SAIDA.write_text(json.dumps(fila, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\ngravado: {SAIDA} ({len(fila)} processos) — consumir com tools/sei_integra_fila.py "
              f"--fila {SAIDA.relative_to(RAIZ)}")
    else:
        print("\n(SIMULAÇÃO — use --gravar para escrever a fila)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
