#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consulta CANÔNICA ao arquivo compacto de processos SEI (leia, não reinvente).

    tools/sei_consultar.py "330020/000762/2021"            # resumo do processo
    tools/sei_consultar.py PROC --fase execucao            # textos de uma fase
    tools/sei_consultar.py PROC --tipo nota_fiscal         # textos de um tipo
    tools/sei_consultar.py PROC --doc 12                   # texto integral do doc
    tools/sei_consultar.py PROC --grep "medição"           # busca com contexto
    tools/sei_consultar.py PROC --fotos                    # fotos de medição
    tools/sei_consultar.py --listar                        # processos arquivados

O arquivo vem de tools/sei_arquivar.py (que vem de sei_integra_completa.py).
Fases/tipos: compliance_agent/sei/fases.py. Barato: é ler txt do disco —
nenhum browser, nenhuma IA, nenhum acesso ao SEI.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ARQUIVO = RAIZ / "data" / "sei_arquivo"


def _tag(proc: str) -> str:
    return re.sub(r"[^0-9]", "_", proc)


def _abrir(proc: str) -> tuple[Path, dict]:
    d = ARQUIVO / _tag(proc)
    m = d / "manifest.json"
    if not m.exists():
        print(f"processo não arquivado: {proc}\n"
              f"1) baixar:   .venv/bin/python tools/sei_integra_completa.py \"{proc}\"\n"
              f"2) arquivar: .venv/bin/python tools/sei_arquivar.py \"{proc}\"")
        sys.exit(1)
    return d, json.loads(m.read_text(encoding="utf-8"))


def _resumo(man: dict) -> str:
    linhas = [f"PROCESSO {man['processo']} · modalidade: {man['modalidade'] or '?'} "
              f"· {len(man['docs'])} docs · {man['fotos_total']} fotos"]
    linhas.append("Linha do tempo: " + " · ".join(
        f"{f}={n}" for f, n in man["linha_do_tempo"].items() if n))
    for l in man.get("lacunas", []):
        icone = "🔴" if l["gravidade"] == "critica" else "🟡"
        linhas.append(f"{icone} LACUNA ({l['gravidade']}): {l['falta']}")
    linhas.append("")
    for d in man["docs"]:
        foto = f" 📷{len(d['fotos'])}" if d.get("fotos") else ""
        ocr = " (ocr)" if d.get("ocr") else ""
        linhas.append(f"  {d['i']:3d} [{d['fase']:<12}] {d['tipo']:<22} "
                      f"{(d['titulo'] or '?')[:48]}{foto}{ocr}")
    return "\n".join(linhas)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("processo", nargs="?", default="")
    ap.add_argument("--fase"); ap.add_argument("--tipo")
    ap.add_argument("--doc", type=int, default=-1)
    ap.add_argument("--grep"); ap.add_argument("--fotos", action="store_true")
    ap.add_argument("--listar", action="store_true")
    args = ap.parse_args()

    if args.listar:
        for d in sorted(ARQUIVO.glob("*/manifest.json")):
            m = json.loads(d.read_text(encoding="utf-8"))
            print(f"{m['processo'] or d.parent.name:24s} {len(m['docs']):4d} docs "
                  f"{m['fotos_total']:4d} fotos  lacunas={len(m['lacunas'])}")
        return 0
    if not args.processo:
        ap.error("informe o processo (ou --listar)")

    raiz, man = _abrir(args.processo)

    if args.fotos:
        for d in man["docs"]:
            for f in d.get("fotos", []):
                print(raiz / f)
        return 0

    if args.doc >= 0:
        for d in man["docs"]:
            if d["i"] == args.doc:
                print((raiz / d["texto"]).read_text(encoding="utf-8"))
                return 0
        print(f"doc {args.doc} não existe"); return 1

    if args.fase or args.tipo:
        for d in man["docs"]:
            if args.fase and d["fase"] != args.fase:
                continue
            if args.tipo and d["tipo"] != args.tipo:
                continue
            print((raiz / d["texto"]).read_text(encoding="utf-8"))
            print("\n" + "─" * 70 + "\n")
        return 0

    if args.grep:
        pad = re.compile(args.grep, re.IGNORECASE)
        for d in man["docs"]:
            txt = (raiz / d["texto"]).read_text(encoding="utf-8")
            for m2 in pad.finditer(txt):
                a, b = max(0, m2.start() - 120), min(len(txt), m2.end() + 120)
                print(f"[doc {d['i']} · {d['fase']} · {(d['titulo'] or '?')[:40]}]")
                print("  …" + txt[a:b].replace("\n", " ") + "…\n")
        return 0

    print(_resumo(man))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
