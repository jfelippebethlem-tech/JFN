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
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
# `JFN_SEI_ARQUIVO` aponta a raiz do acervo para outro lugar — usado pelo teste, que precisa montar
# um processo com documento sem teor sem sujar o acervo real.
ARQUIVO = Path(os.environ.get("JFN_SEI_ARQUIVO") or (RAIZ / "data" / "sei_arquivo"))


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


def _ler_texto(raiz, d):
    """Teor do documento, ou `None` quando o acervo não o tem.

    `texto` vazio no manifesto faz `raiz / ""` apontar para o DIRETÓRIO do processo — o
    `read_text` levanta `IsADirectoryError` e derruba quem estiver varrendo. Devolver `None` deixa
    o chamador DECLARAR a lacuna em vez de morrer no meio dela.
    """
    caminho = str(d.get("texto") or "").strip()
    if not caminho:
        return None
    try:
        return (raiz / caminho).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


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
                txt = _ler_texto(raiz, d)
                if txt is None:
                    print(f"doc {args.doc} está no manifesto e SEM TEOR no acervo — "
                          f"'{d.get('titulo') or '?'}'. Não é documento vazio: é captura que "
                          f"não trouxe o conteúdo.")
                    return 1
                print(txt)
                return 0
        print(f"doc {args.doc} não existe"); return 1

    if args.fase or args.tipo:
        for d in man["docs"]:
            if args.fase and d["fase"] != args.fase:
                continue
            if args.tipo and d["tipo"] != args.tipo:
                continue
            txt = _ler_texto(raiz, d)
            if txt is None:
                print(f"[doc {d['i']}] SEM TEOR no acervo — '{(d.get('titulo') or '?')[:60]}'")
            else:
                print(txt)
            print("\n" + "─" * 70 + "\n")
        return 0

    if args.grep:
        pad = re.compile(args.grep, re.IGNORECASE)
        sem_texto = 0
        for d in man["docs"]:
            # DOCUMENTO SEM TEOR NÃO PODE DERRUBAR A BUSCA. Quando `texto` vem vazio no manifesto,
            # `raiz / ""` é o próprio DIRETÓRIO e o `read_text` levanta `IsADirectoryError` —
            # medido em 2026-08-11 lendo o processo da AGILE/SEEDUC: a busca morreu no doc 21 e
            # engoliu tudo que vinha depois. Uma varredura que para no meio e não avisa é a pior
            # forma de subnotificar: parece resposta completa. Conta e DECLARA no fim.
            txt = _ler_texto(raiz, d)
            if txt is None:
                sem_texto += 1
                continue
            for m2 in pad.finditer(txt):
                a, b = max(0, m2.start() - 120), min(len(txt), m2.end() + 120)
                print(f"[doc {d['i']} · {d['fase']} · {(d['titulo'] or '?')[:40]}]")
                print("  …" + txt[a:b].replace("\n", " ") + "…\n")
        if sem_texto:
            print(f"⚠️  {sem_texto} de {len(man['docs'])} documentos SEM TEOR no acervo não foram "
                  f"varridos — a ausência de ocorrência neles NÃO é ausência no processo.")
        return 0

    print(_resumo(man))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
