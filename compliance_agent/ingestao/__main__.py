# -*- coding: utf-8 -*-
"""CLI só-leitura do contrato de ingestão.

    python -m compliance_agent.ingestao validar                  # contrato + cobertura das fontes da propagação
    python -m compliance_agent.ingestao medir --db CAMINHO [--fonte ID ...] [--amostra N]

`medir` abre o banco em modo SÓ-LEITURA (`mode=ro`; com --imutavel, `immutable=1` para snapshot congelado)
e imprime os 6 sensores por fonte em JSON. Nunca escreve, nunca toca a rede.
"""
from __future__ import annotations

import argparse
import json
import sys

from compliance_agent.ingestao import contrato as ct
from compliance_agent.ingestao import sensores


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m compliance_agent.ingestao")
    ap.add_argument("acao", choices=("validar", "medir"))
    ap.add_argument("--contrato", default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--imutavel", action="store_true", help="snapshot congelado (immutable=1)")
    ap.add_argument("--fonte", action="append", default=[])
    ap.add_argument("--amostra", type=int, default=sensores.AMOSTRA)
    a = ap.parse_args(argv)
    c = ct.carregar(a.contrato)
    if a.acao == "validar":
        cob = ct.conferir_propagacao(c, ct.fontes_da_propagacao())
        print(json.dumps({"versao": c.versao, "fontes": len(c.fontes),
                          "externas": sum(f.natureza == "externa" for f in c.fontes.values()), **cob},
                         ensure_ascii=False, indent=2))
        return 0 if not cob["faltam"] and not cob["inexistentes"] else 1
    if not a.db:
        ap.error("medir exige --db")
    import sqlite3
    uri = f"file:{a.db}?{'immutable=1' if a.imutavel else 'mode=ro'}"
    con = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        alvo = a.fonte or [k for k, f in c.fontes.items() if f.natureza == "externa" and f.banco == "compliance"]
        saida = [sensores.medir_fonte(con, k, c.fontes[k], amostra=a.amostra) for k in alvo]
    finally:
        con.close()
    print(json.dumps(saida, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
