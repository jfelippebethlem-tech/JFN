#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrai o CSS e o JS inline do painel para arquivos servidos com gzip e cache.

O PROBLEMA, MEDIDO. `static/jfn-painel.html` tem 519 KB: 178 KB de CSS e 337 KB de JS **inline**, sem
compressão, sem cache e sem build. Toda carga do painel arrasta os 519 KB pela rede e o navegador
precisa parsear os 337 KB de JS antes do primeiro pixel útil.

POR QUE ESTE SCRIPT E NÃO UM BUNDLER. Não há toolchain, e introduzir uma num painel de 60 abas sem
especificação fora do próprio código — com um walker que só verifica ausência de erro — seria trocar
um problema medido por um risco não medido. Aqui a transformação é textual e reversível: o conteúdo
sai do arquivo e é referenciado, byte a byte igual.

A ORDEM IMPORTA E NÃO É NEGOCIÁVEL:
  1. CSS primeiro. É inerte: valida servir + gzip + cache + catraca sem arriscar o boot.
  2. Só depois o JS, em UM arquivo, **sem `type=module`, sem `defer`, sem `async`**, na EXATA posição
     do inline. `type=module` muda escopo e timing (defer implícito + TDZ mais estrito) e é
     precisamente o vetor que já matou o boot do painel três vezes.

CACHE: o nome do arquivo é fixo e o `?v=<hash8>` no link muda com o conteúdo. Assim o navegador pode
cachear para sempre e ainda assim receber a versão nova no mesmo instante em que ela existe.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.painel_extrair --css          # etapa 1
    PYTHONPATH=. .venv/bin/python -m tools.painel_extrair --js           # etapa 2
    PYTHONPATH=. .venv/bin/python -m tools.painel_extrair --css --js
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_HTML = _REPO / "static" / "jfn-painel.html"
_CSS = _REPO / "static" / "css" / "painel.css"
_JS = _REPO / "static" / "js" / "painel.js"

_RE_STYLE = re.compile(r"<style>(.*?)</style>", re.S)
# script inline = sem atributo src
_RE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", re.S)


def _hash8(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:8]


def extrair_css(html: str) -> tuple[str, str] | None:
    m = _RE_STYLE.search(html)
    if not m:
        return None
    css = m.group(1)
    _CSS.parent.mkdir(parents=True, exist_ok=True)
    _CSS.write_text(css, encoding="utf-8")
    link = f'<link rel="stylesheet" href="/static/css/painel.css?v={_hash8(css)}">'
    return html[: m.start()] + link + html[m.end():], f"CSS {len(css)} bytes -> {_CSS}"


def extrair_js(html: str) -> tuple[str, str] | None:
    achados = list(_RE_SCRIPT.finditer(html))
    if len(achados) != 1:
        raise SystemExit(
            f"esperado exatamente 1 <script> inline, achei {len(achados)} — "
            "extrair vários em um arquivo mudaria a ORDEM de execução; pare e reveja à mão")
    m = achados[0]
    atributos = (m.group(1) or "").strip()
    if atributos:
        raise SystemExit(f"o <script> inline tem atributos ({atributos!r}) — reveja à mão")
    js = m.group(2)
    _JS.parent.mkdir(parents=True, exist_ok=True)
    _JS.write_text(js, encoding="utf-8")
    # sem type=module / defer / async: mesmo escopo e mesmo timing do inline que ele substitui
    tag = f'<script src="/static/js/painel.js?v={_hash8(js)}"></script>'
    return html[: m.start()] + tag + html[m.end():], f"JS {len(js)} bytes -> {_JS}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--css", action="store_true")
    ap.add_argument("--js", action="store_true")
    a = ap.parse_args()
    if not (a.css or a.js):
        print(__doc__)
        return 2

    original = _HTML.read_text(encoding="utf-8")
    backup = _HTML.with_suffix(".html.antes-extracao")
    if not backup.exists():
        shutil.copy2(_HTML, backup)
        print(f"backup: {backup}")

    html = original
    for etapa, fn in (("css", extrair_css), ("js", extrair_js)):
        if not getattr(a, etapa):
            continue
        r = fn(html)
        if r is None:
            print(f"nada a extrair em {etapa}")
            continue
        html, msg = r
        print(msg)

    _HTML.write_text(html, encoding="utf-8")
    print(f"HTML {len(original)} -> {len(html)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
