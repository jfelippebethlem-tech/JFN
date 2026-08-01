#!/usr/bin/env python3
"""Screen R025 (Cardinal/OCP) — PERDEDOR CONTUMAZ: licitante que participa muito e (quase)
nunca vence. Na literatura de cartel é assinatura de *cover bidding*: a empresa existe nos
certames para simular concorrência e perder. Fonte: `tcerj_licitante` (participante×resultado).

Honestidade: participação baixa não conta (min-part); perder muito TAMBÉM é o normal de
mercado competitivo — o sinal só interessa quando o perdedor orbita SEMPRE os mesmos
vencedores/órgãos (coluna `vencedores_orbitados`). Screen = fila de apuração, nunca veredito.

Uso: tools/screen_perdedor_contumaz.py [--min-part 8] [--top 20]
"""
import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-part", type=int, default=8)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{REPO / 'data' / 'compliance.db'}?mode=ro", uri=True)
    rows = con.execute(
        "select processo, ente, participante, resultado from tcerj_licitante "
        "where participante is not null and participante <> ''").fetchall()

    stats: dict[str, Counter] = defaultdict(Counter)
    vencedor_por_proc: dict[str, set] = defaultdict(set)
    procs_por_part: dict[str, set] = defaultdict(set)
    entes_por_part: dict[str, Counter] = defaultdict(Counter)
    for proc, ente, part, res in rows:
        r = (res or "").upper()
        stats[part][r] += 1
        procs_por_part[part].add(proc)
        entes_por_part[part][ente or "?"] += 1
        if "VENCEDOR" in r:
            vencedor_por_proc[proc].add(part)

    fila = []
    for part, c in stats.items():
        n = sum(c.values())
        if n < args.min_part:
            continue
        vit = sum(v for k, v in c.items() if "VENCEDOR" in k)
        taxa = vit / n
        if taxa > 0.10:
            continue
        # com quem este perdedor orbita: vencedores dos certames em que ele perdeu
        orbita: Counter = Counter()
        for proc in procs_por_part[part]:
            for v in vencedor_por_proc.get(proc, ()):
                if v != part:
                    orbita[v] += 1
        top_orb = orbita.most_common(2)
        # concentração de órbita: perde sempre p/ o MESMO vencedor = sinal muito mais forte
        conc = (top_orb[0][1] / max(1, n - vit)) if top_orb else 0.0
        fila.append({"participante": part, "n": n, "vitorias": vit,
                     "taxa": round(100 * taxa, 1), "conc_orbita": round(100 * conc, 1),
                     "orbita": [f"{v} ({k}x)" for v, k in top_orb],
                     "entes": [e for e, _ in entes_por_part[part].most_common(2)]})

    fila.sort(key=lambda x: (-x["conc_orbita"], -x["n"]))
    for i, f in enumerate(fila[: args.top], 1):
        print(f"{i:3d}. {f['participante'][:52]:52} part={f['n']:3d} vit={f['vitorias']} "
              f"({f['taxa']}%) · órbita {f['conc_orbita']}% → {'; '.join(f['orbita'])[:70]}")
    print(f"\n{len(fila)} perdedores contumazes (≥{args.min_part} part., ≤10% vitória) "
          f"de {len(stats)} licitantes", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
