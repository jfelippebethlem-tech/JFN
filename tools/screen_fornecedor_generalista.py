#!/usr/bin/env python3
"""Screen R048 (Cardinal/OCP) — FORNECEDOR GENERALISTA: vence em ramos díspares demais.

Empresa que ganha licitação de medicamento E obra de engenharia E gêneros alimentícios não é
especialista em nada — é assinatura de intermediário/fachada (heterogeneous supplier, R048).
Fonte: `tcerj_licitante` (vitórias × tipologia). Baldes catch-all (OUTRAS COMPRAS/OUTROS
SERVIÇOS/CHAMAMENTO) NÃO contam como ramo — só tipologia específica. Screen = fila, não veredito.

Uso: tools/screen_fornecedor_generalista.py [--min-ramos 4] [--top 20]
"""
import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_CATCH_ALL = ("OUTRAS", "OUTROS", "CHAMAMENTO", "?")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-ramos", type=int, default=4)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{REPO / 'data' / 'compliance.db'}?mode=ro", uri=True)
    rows = con.execute(
        "select participante, tipologia, ente from tcerj_licitante "
        "where resultado like '%VENCEDOR%' and participante <> ''").fetchall()

    ramos: dict[str, set] = defaultdict(set)
    n_vit: dict[str, int] = defaultdict(int)
    entes: dict[str, set] = defaultdict(set)
    for part, tip, ente in rows:
        n_vit[part] += 1
        entes[part].add(ente or "?")
        t = (tip or "?").upper()
        if not any(t.startswith(c) for c in _CATCH_ALL):
            ramos[part].add(t)

    fila = [{"participante": p, "n_ramos": len(r), "ramos": sorted(r),
             "vitorias": n_vit[p], "n_entes": len(entes[p])}
            for p, r in ramos.items() if len(r) >= args.min_ramos]
    fila.sort(key=lambda x: (-x["n_ramos"], -x["vitorias"]))
    for i, f in enumerate(fila[: args.top], 1):
        print(f"{i:3d}. {f['participante'][:48]:48} ramos={f['n_ramos']} vit={f['vitorias']:3d} "
              f"entes={f['n_entes']:2d} · {'; '.join(r[:22] for r in f['ramos'][:5])}")
    print(f"\n{len(fila)} generalistas (≥{args.min_ramos} ramos específicos vencidos)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
