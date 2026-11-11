#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v61_contraste — mede WCAG 2.1 (AA = 4,5:1) de todos os pares tinta/fundo do tema «Gelo».

Lê os tokens do próprio estrato (`static/css/src/99z2-v61-10-tema.css`): se o CSS mudar, a medida
muda junto. Superfície translúcida é composta sobre o PIOR fundo (o mais escuro, --bg-3) antes de
medir. Sai com código 1 se algum par usado como TEXTO ficar abaixo de 4,5:1.

Uso: .venv/bin/python tools/v61_contraste.py [--md]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_CSS = Path(__file__).resolve().parent.parent / "static" / "css" / "src" / "99z2-v61-10-tema.css"


def _rgba(v: str):
    v = v.strip()
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (1.0,)
    m = re.match(r"rgba?\(([^)]+)\)", v)
    if not m:
        return None
    p = [x.strip() for x in m.group(1).split(",")]
    return (float(p[0]), float(p[1]), float(p[2]), float(p[3]) if len(p) > 3 else 1.0)


def _sobre(cima, baixo):
    a = cima[3]
    return tuple(cima[i] * a + baixo[i] * (1 - a) for i in range(3)) + (1.0,)


def _lum(c):
    def f(x):
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def razao(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def tokens() -> dict:
    out = {}
    for nome, val in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;}]+)", _CSS.read_text(encoding="utf-8")):
        c = _rgba(val)
        if c and nome not in out:
            out[nome] = c
    return out


# tinta usada como TEXTO → tem de dar AA em todos os fundos
TEXTO = ["--ink", "--ink-2", "--muted", "--ion-text", "--money-text", "--ok-text", "--warn-text", "--crit-text"]
# tokens do brief usados só como PREENCHIMENTO/traço — medidos para registro, não reprovam
PREENCHE = ["--ink-3", "--ion", "--cyan", "--ok", "--warn", "--crit", "--money"]
FUNDOS = ["--bg", "--bg-2", "--bg-3", "--surface-solid", "--surface", "--surface-2"]


def medir():
    t = tokens()
    pior = t["--bg-3"]
    linhas, falhas = [], []
    for nome in TEXTO + PREENCHE:
        for f in FUNDOS:
            fundo = t[f] if t[f][3] == 1 else _sobre(t[f], pior)
            r = razao(t[nome], fundo)
            texto = nome in TEXTO
            linhas.append((nome, f, r, texto))
            if texto and r < 4.5:
                falhas.append((nome, f, r))
    # branco sobre os fundos cheios dos controles ativos
    for f in ("--ion-solid", "--ion-text", "--ion"):
        r = razao((255, 255, 255, 1), t[f])
        texto = f != "--ion"
        linhas.append(("#FFFFFF", f, r, texto))
        if texto and r < 4.5:
            falhas.append(("#FFFFFF", f, r))
    return linhas, falhas


def main() -> int:
    linhas, falhas = medir()
    md = "--md" in sys.argv
    if md:
        print("| tinta | fundo | razão | uso | AA |")
        print("|---|---|---:|---|:---:|")
    for nome, f, r, texto in linhas:
        ok = "✔" if r >= 4.5 else ("✘" if texto else "—")
        uso = "texto" if texto else "preenchimento"
        print(f"| `{nome}` | `{f}` | {r:.2f}:1 | {uso} | {ok} |" if md
              else f"{nome:14s} sobre {f:16s} {r:5.2f}:1  {uso:13s} {ok}")
    print(("\n" if md else "") + (f"FALHAS de texto: {len(falhas)}" if falhas else "AA: todos os pares de TEXTO >= 4,5:1"))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
