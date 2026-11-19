"""Roda todos os detectores de `compliance_agent/padroes/` (ou um, com --id) e grava `data/padroes/<id>.json`.

Contrato em docs/PADROES-DE-IRREGULARIDADE.md. Uso: nice -n 19 .venv/bin/python -m tools.padroes_varrer [--id X] [--limite N]
"""
from __future__ import annotations

import argparse
import importlib
import json
import pkgutil
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
SAIDA = RAIZ / "data" / "padroes"


def ids() -> list[str]:
    import compliance_agent.padroes as pac
    return sorted(m.name for m in pkgutil.iter_modules(pac.__path__) if not m.name.startswith("_"))


def rodar(id_: str, limite: int | None = None) -> dict:
    mod = importlib.import_module(f"compliance_agent.padroes.{id_}")
    t0 = time.time()
    r = mod.varrer(limite=limite)
    r["segundos"] = round(time.time() - t0, 1)
    SAIDA.mkdir(parents=True, exist_ok=True)
    tmp = SAIDA / f"{id_}.json.tmp"
    tmp.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(SAIDA / f"{id_}.json")
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", action="append")
    ap.add_argument("--limite", type=int)
    a = ap.parse_args(argv)
    for i in a.id or ids():
        r = rodar(i, a.limite)
        print(json.dumps({"id": i, "universo": r.get("universo"), "achados": len(r.get("achados") or []),
                          "segundos": r["segundos"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
