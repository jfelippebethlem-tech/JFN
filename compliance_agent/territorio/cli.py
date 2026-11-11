# -*- coding: utf-8 -*-
"""CLI do motor território.

    python -m compliance_agent.territorio.cli --full          # refaz tudo (inclui o vínculo de OBs)
    python -m compliance_agent.territorio.cli --incremental   # só contrato novo ou alterado

Trava `data/territorio.lock` (flock): duas execuções ao mesmo tempo nunca escrevem juntas. Pesado só
no `--full` (uma leitura corrida das OBs do SIAFE, ~1,3 mi de linhas, em modo somente-leitura).
"""
from __future__ import annotations

import argparse
import fcntl
import sys
import time

from compliance_agent.territorio import agrega, atribui_estado, atribui_pcrj, base


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Motor território: contratos do Estado por município e da PCRJ por AP")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--full", action="store_true", help="refaz todas as atribuições")
    g.add_argument("--incremental", action="store_true", help="só contratos novos ou alterados")
    ap.add_argument("--so", choices=["estado", "pcrj"], help="roda só um dos lados")
    a = ap.parse_args(argv)
    base.DATA.mkdir(parents=True, exist_ok=True)
    trava = open(base.DATA / "territorio.lock", "w")
    try:
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[territorio] outra execução em curso (territorio.lock) — saindo", flush=True)
        return 0
    t0 = time.time()
    log = lambda m: print(m, flush=True)  # noqa: E731
    log(f"[territorio] início ({'completo' if a.full else 'incremental'})")
    if a.so != "pcrj":
        atribui_estado.rodar(incremental=a.incremental, log=log)
    if a.so != "estado":
        atribui_pcrj.rodar(incremental=a.incremental, log=log)
    agrega.rodar(log=log)
    log(f"[territorio] fim em {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
