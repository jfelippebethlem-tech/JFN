#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Materializa o levantamento de co-contato em certame — o cálculo não cai dentro do request.

`compliance_agent/osint/cocontato_certame.levantar` varre 4.517 certames e cruza 5.624 CNPJs
contra 6,17 milhões de estabelecimentos: 40 s por passada. Rota que faz isso a cada clique é rota
que o usuário conclui estar quebrada — é a mesma regra de `/api/tac/ranking` e da fila de agente
público.

    python -m tools.cocontato_certame
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
SAIDA = _REPO / "data" / "cocontato_certame.json"


def gravar(db: str = "") -> dict:
    from compliance_agent.osint.cocontato_certame import levantar
    from compliance_agent.reporting.intel_base import _DB

    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True)
    try:
        r = levantar(con)
    finally:
        con.close()
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps({"gerado_em": time.strftime("%Y-%m-%d %H:%M"), **r},
                                ensure_ascii=False), encoding="utf-8")
    return {k: v for k, v in r.items() if k != "pares"} | {"arquivo": str(SAIDA)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args()
    for k, v in gravar().items():
        print(f"{k:24s} {v}")


if __name__ == "__main__":
    main()
