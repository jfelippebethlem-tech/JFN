# -*- coding: utf-8 -*-
"""CLI do motor de fluxo.

    python -m compliance_agent.fluxo supervisor --no vm1 [--uma-volta] [--isolamento auto|systemd|subprocesso]
    python -m compliance_agent.fluxo saude [--esperados vm1,vm2,itcampo]
    python -m compliance_agent.fluxo eco <chave>        # enfileira um job E0 de teste (prova ponta a ponta)
O schema: `python -m compliance_agent.fluxo.schema verificar|aplicar`.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from compliance_agent.fluxo import fila, planejador
from compliance_agent.fluxo.supervisor import Supervisor


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m compliance_agent.fluxo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("supervisor")
    s.add_argument("--no", required=True)
    s.add_argument("--uma-volta", action="store_true", help="uma volta, espera os filhos dela e sai")
    s.add_argument("--isolamento", default="auto", choices=("auto", "systemd", "subprocesso"))
    h = sub.add_parser("saude")
    h.add_argument("--esperados", default="")
    e = sub.add_parser("eco")
    e.add_argument("chave")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if a.cmd == "supervisor":
        sup = Supervisor(no=a.no, isolamento=a.isolamento)
        if a.uma_volta:
            r = sup.uma_volta()
            r["drenados"] = sup.drenar()
            sup.fechar()
            print(json.dumps(r, ensure_ascii=False, default=str))
            return 0
        sup.rodar()
        return 0
    con = fila.conectar()
    try:
        if a.cmd == "saude":
            r = planejador.saude(con, tuple(n for n in a.esperados.split(",") if n))
        else:
            r = {"id": fila.enfileirar(con, "eco", f"eco:{a.chave}", {"origem": "cli"})}
    finally:
        con.close()
    print(json.dumps(r, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
