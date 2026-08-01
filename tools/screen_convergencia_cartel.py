#!/usr/bin/env python3
"""Convergência de screens de cartel — R025 (perdedor contumaz) × R048 (generalista).

A ideia que os screens isolados não dão: **um vencedor generalista (vence em ramos díspares)
que é ORBITADO por perdedores contumazes** é o núcleo de um arranjo, não uma coincidência de
mercado. Isoladamente cada screen tem FP estrutural conhecido (farma orbita farma; distribuidora
regional é generalista por natureza); a interseção é o que merece a fila do fiscal.

Também emite o mapa **licitante-viajante**: contumaz que aparece em MUITOS municípios distintos
sem nunca vencer (custo de participar sem expectativa de ganhar = sinal de serviço a terceiro).

Uso: tools/screen_convergencia_cartel.py [--min-part 8] [--min-ramos 4] [--md]
"""
import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_CATCH_ALL = ("OUTRAS", "OUTROS", "CHAMAMENTO", "?")
# ramos onde a órbita alta é ESTRUTURAL (mercado concentrado por natureza) — declarado, não escondido
_FP_ESTRUTURAL = ("MEDICAMENTOS", "MATERIAL HOSPITALAR")


def coletar(con) -> dict:
    rows = con.execute("select processo, participante, resultado, tipologia, ente "
                       "from tcerj_licitante where participante <> ''").fetchall()
    d = {"stats": defaultdict(Counter), "venc_proc": defaultdict(set), "procs": defaultdict(set),
         "ramos": defaultdict(set), "entes": defaultdict(set), "tip_part": defaultdict(Counter)}
    for proc, part, res, tip, ente in rows:
        r = (res or "").upper()
        t = (tip or "?").upper()
        d["stats"][part][r] += 1
        d["procs"][part].add(proc)
        d["entes"][part].add(ente or "?")
        d["tip_part"][part][t] += 1
        if "VENCEDOR" in r:
            d["venc_proc"][proc].add(part)
            if not t.startswith(_CATCH_ALL):
                d["ramos"][part].add(t)
    return d


def contumazes(d: dict, min_part: int, min_conc: float = 0.4) -> list[dict]:
    saida = []
    for part, c in d["stats"].items():
        n = sum(c.values())
        vit = sum(v for k, v in c.items() if "VENCEDOR" in k)
        if n < min_part or (vit / n) > 0.10:
            continue
        orb = Counter()
        for proc in d["procs"][part]:
            for v in d["venc_proc"].get(proc, ()):
                if v != part:
                    orb[v] += 1
        if not orb:
            continue
        top, k = orb.most_common(1)[0]
        conc = k / max(1, n - vit)
        if conc < min_conc:
            continue
        estrutural = any(any(t.startswith(f) for f in _FP_ESTRUTURAL)
                         for t, _ in d["tip_part"][part].most_common(2))
        saida.append({"perdedor": part, "n": n, "vitorias": vit, "orbita": top,
                      "conc": round(100 * conc, 1), "n_entes": len(d["entes"][part]),
                      "fp_estrutural": estrutural})
    return saida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-part", type=int, default=8)
    ap.add_argument("--min-ramos", type=int, default=4)
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{REPO / 'data' / 'compliance.db'}?mode=ro", uri=True)
    d = coletar(con)
    cont = contumazes(d, args.min_part)

    por_vencedor: dict[str, list] = defaultdict(list)
    for c in cont:
        por_vencedor[c["orbita"]].append(c)

    nucleos = []
    for venc, orbitantes in por_vencedor.items():
        n_ramos = len(d["ramos"].get(venc, ()))
        if n_ramos < args.min_ramos:
            continue
        vit = sum(v for k, v in d["stats"][venc].items() if "VENCEDOR" in k)
        nucleos.append({"vencedor": venc, "n_ramos": n_ramos, "vitorias": vit,
                        "n_entes": len(d["entes"][venc]),
                        "orbitantes": sorted(orbitantes, key=lambda x: -x["conc"]),
                        "so_estrutural": all(o["fp_estrutural"] for o in orbitantes)})
    nucleos.sort(key=lambda x: (-len(x["orbitantes"]), -x["n_ramos"], -x["vitorias"]))

    if args.md:
        print("| Vencedor generalista | Ramos | Vitórias | Entes | Perdedores contumazes na órbita |")
        print("|---|---|---|---|---|")
        for nu in nucleos:
            orb = "; ".join(f"{o['perdedor'][:28]} ({o['n']}p/{o['vitorias']}v, {o['conc']}%)"
                            for o in nu["orbitantes"][:3])
            print(f"| {nu['vencedor'][:40]} | {nu['n_ramos']} | {nu['vitorias']} "
                  f"| {nu['n_entes']} | {orb} |")
    else:
        for i, nu in enumerate(nucleos, 1):
            marca = " [FP estrutural provável]" if nu["so_estrutural"] else ""
            print(f"{i:3d}. {nu['vencedor'][:46]:46} ramos={nu['n_ramos']} vit={nu['vitorias']:3d} "
                  f"entes={nu['n_entes']:2d} · {len(nu['orbitantes'])} orbitante(s){marca}")
            for o in nu["orbitantes"][:3]:
                print(f"       ↳ {o['perdedor'][:44]:44} {o['n']}part/{o['vitorias']}vit "
                      f"órbita {o['conc']}% · {o['n_entes']} municípios")

    viajantes = sorted([c for c in cont if c["n_entes"] >= 3],
                       key=lambda x: -x["n_entes"])[:8]
    print("\nLicitante-viajante (contumaz em ≥3 municípios):", file=sys.stderr)
    for v in viajantes:
        print(f"   {v['perdedor'][:44]:44} {v['n_entes']} municípios · {v['n']}part/"
              f"{v['vitorias']}vit", file=sys.stderr)
    print(f"\n{len(nucleos)} núcleos (generalista orbitado) de {len(cont)} contumazes",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
