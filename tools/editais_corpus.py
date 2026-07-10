#!/usr/bin/env python3
"""Runner: baixa o corpus de editais municipais. Uso: tools/editais_corpus.py [--limite N]"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compliance_agent.coleta_lock import coleta_lock  # noqa: E402
from compliance_agent.editais import corpus  # noqa: E402
from compliance_agent.editais import db as ed  # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=None)
    args = ap.parse_args()
    with coleta_lock():
        con = ed.conectar()
        ed.init_schema(con)
        print(await corpus.coletar_corpus(con, limite=args.limite), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
