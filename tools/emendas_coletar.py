#!/usr/bin/env python3
"""Runner: roster Câmara + emendas 2019–2026 (retomável).

Uso: .venv/bin/python tools/emendas_coletar.py [--anos 2019 2020 ...] [--pausa 1.0]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from compliance_agent.emendas import camara, coletor  # noqa: E402
from compliance_agent.emendas import db as edb  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anos", nargs="*", type=int, default=list(range(2019, 2027)))
    ap.add_argument("--pausa", type=float, default=1.0)
    args = ap.parse_args()
    con = edb.conectar()
    edb.init_schema(con)
    r = camara.listar_deputados_rj()
    if not r["verificado"]:
        print(f"INDISPONÍVEL: {r['motivo']}")
        sys.exit(2)
    print(f"roster: {camara.gravar_roster(con, r['deputados'])} deputados", flush=True)
    for ano in args.anos:
        res = coletor.coletar_ano(con, ano, pausa=args.pausa)
        print(f"{ano}: {res}", flush=True)
        if not res["verificado"]:
            sys.exit(2)     # supervisor/cron pode reexecutar — checkpoint retoma


if __name__ == "__main__":
    main()
