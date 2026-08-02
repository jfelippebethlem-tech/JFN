#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""painel_css_cortar — quebra o painel.css em estratos e prova que nada mudou.

POR QUE O CORTE E ESTRATIGRAFICO E NAO SEMANTICO. O `painel.css` e sedimentar: `.btn` e declarado
em 14 pontos, `.card::after` em tres geracoes, `:active` em quatro. Cada estrato sobrescreve o
anterior POR ORDEM DE CASCATA — e por isso nao e possivel, na mesma passada, preservar a cascata E
agrupar por semantica. Juntar os quatro `.btn` num `componentes/botao.css` seria REESCREVER a
cascata, nao mover arquivo.

Entao o corte e pela ordem em que as coisas foram escritas: `00-`, `10-`, `20-`… Menos bonito, e o
unico provavel a byte.

A PROVA E ARITMETICA, nao visual: `sha256(concat(src/*.css)) == sha256(painel.css)`. Se bater, o
`test_painel_css_integro` passa sem uma linha alterada — inclusive o teste que compara substrings
literais de regras que a casa ja perdeu uma vez. Nenhum reformatador, nenhum prettier, nenhum
postcss. Um corte, nao um rewrite.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.painel_css_cortar          # corta
    PYTHONPATH=. .venv/bin/python -m tools.painel_css_cortar --juntar # concatena src/ -> painel.css
    PYTHONPATH=. .venv/bin/python -m tools.painel_css_cortar --check  # so verifica a identidade
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_CSS = _REPO / "static" / "css" / "painel.css"
_SRC = _REPO / "static" / "css" / "src"

# (prefixo numerico, nome, primeira linha EXATA do estrato). A ordem aqui E a ordem da cascata;
# mudar um prefixo muda quem vence. O ultimo estrato vai ate o fim do arquivo.
_ESTRATOS = [
    ("00", "v7-base", None),          # do inicio ate o marcador seguinte
    ("70", "v49-sobrio", "/* ══ v49 · MODO SÓBRIO MEDIDO"),
    ("75", "v49-mestras", "/* ── v49 · FUNÇÕES MESTRAS no cockpit"),
    ("80", "v54", "/* ══ v54 · O NÚMERO SAI INTEIRO"),
    ("85", "v55", "/* ══ v55 · A MESMA SALA, VISTA DE OUTRO PONTO"),
    ("90", "v57", "/* ══ v57 · A VARREDURA QUE FALTAVA"),
    ("95", "v58", "/* ══════════════════════════════════════════════════════════════════════════"
                  "════════════════════\n   v58 — O RELÓGIO."),
]


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _fatiar(css: str) -> list[tuple[str, str]]:
    """Devolve [(nome-do-arquivo, conteudo)] na ordem da cascata."""
    cortes = []
    for pref, nome, marca in _ESTRATOS:
        if marca is None:
            cortes.append((f"{pref}-{nome}.css", 0))
            continue
        i = css.find(marca)
        if i < 0:
            raise SystemExit(f"marcador do estrato {pref}-{nome} nao encontrado:\n  {marca[:70]}")
        cortes.append((f"{pref}-{nome}.css", i))
    fora = []
    for k, (arq, ini) in enumerate(cortes):
        fim = cortes[k + 1][1] if k + 1 < len(cortes) else len(css)
        fora.append((arq, css[ini:fim]))
    return fora


def juntar() -> str:
    """Concatena `src/*.css` na ordem dos prefixos. E o build do CSS: concatenacao pura."""
    partes = sorted(_SRC.glob("*.css"))
    return "".join(p.read_text(encoding="utf-8") for p in partes)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--juntar", action="store_true", help="src/ -> painel.css")
    ap.add_argument("--check", action="store_true", help="so verifica a identidade byte a byte")
    a = ap.parse_args(argv)

    if a.juntar or a.check:
        if not _SRC.is_dir():
            print("[css] static/css/src/ nao existe — nada a juntar")
            return 0
        novo = juntar()
        atual = _CSS.read_text(encoding="utf-8")
        if novo == atual:
            print(f"[css] src/ e painel.css sao IDENTICOS ({len(novo)} bytes, "
                  f"sha256 {_hash(novo)[:12]})")
            return 0
        if a.check:
            print(f"[css] DIVERGEM — src/ concatenado tem {len(novo)} bytes e painel.css tem "
                  f"{len(atual)}.\n      Rode `--juntar` (o CSS e gerado por concatenacao; "
                  f"edite os estratos em static/css/src/).", file=sys.stderr)
            return 1
        _CSS.write_text(novo, encoding="utf-8")
        print(f"[css] painel.css reconstruido de src/ ({len(novo)} bytes)")
        return 0

    css = _CSS.read_text(encoding="utf-8")
    _SRC.mkdir(parents=True, exist_ok=True)
    partes = _fatiar(css)
    for arq, conteudo in partes:
        (_SRC / arq).write_text(conteudo, encoding="utf-8")
        print(f"  {arq:22s} {len(conteudo):>7d} bytes")
    remontado = juntar()
    ok = remontado == css
    print(f"\nsha256 original : {_hash(css)}")
    print(f"sha256 remontado: {_hash(remontado)}")
    print("IDENTICOS — o corte nao mudou um byte." if ok
          else "DIVERGEM — o corte perdeu ou duplicou conteudo. NAO use.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
