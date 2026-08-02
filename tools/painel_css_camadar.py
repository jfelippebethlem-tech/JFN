#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""painel_css_camadar — poe os estratos do painel em `@layer`, e tira do caminho o que nao pode ir.

O §6.2-A do `PAINEL-v58-ESTADO-E-CONTINUACAO`. Ele vem com um plano e uma premissa; a premissa
estava errada, e este cabecalho existe para registrar a correcao antes que alguem repita o erro.

    "A familia de degradacao fica FORA de camada e por ultimo. Para `!important` a ordem de
     camadas e INVERTIDA, e os 16 `!important` do arquivo estao todos nela."

MEDIDO com contagem de chaves (o `grep` engana: ele acha o `@media` mais proximo ACIMA, que
frequentemente nao e o que envolve a regra): sao 15 declaracoes `!important`, e SETE NAO estao na
familia de degradacao. Tres delas sao a MESMA regra em tres geracoes —
`nav.tabs button.on::after`, em `00-v7-base`, `00-v7-base` de novo e `95-v58` — duelando por
`!important` e resolvidas hoje por ORDEM DE DOCUMENTO, que e o que faz a v58 (a respiracao da aba
derivando do relogio, `var(--bpm)`) vencer.

Camadar ingenuamente INVERTE esse duelo: em `!important`, a camada mais BAIXA ganha, entao a regra
de `00-v7-base` passaria a vencer e a respiracao da aba pararia de derivar do relogio. O recurso
inteiro do v58 seria desfeito sem um erro no console, sem um teste quebrado e sem nada em revisao
de codigo. Nao era a familia de degradacao; era um duelo de tres geracoes que ninguem tinha
contado.

═══ A REGRA DESTA FERRAMENTA ═══

Toda regra que contenha `!important` sai da camada e vai para a CAUDA NAO-CAMADADA, na ordem
original. Com isso:
  · os duelos de `!important` continuam sendo resolvidos por ordem de documento — identico a hoje;
  · as declaracoes NORMAIS que viajam na mesma regra sobem de forca (nao-camadado vence camadado).
    Este e o efeito colateral inevitavel, e e por isso que esta ferramenta NAO tem o direito de
    decidir sozinha se pode entrar: quem decide e o `painel_computado`, comparando o estilo
    computado das 60 abas em duas larguras, antes e depois. Diff vazio, entra. Diff nao vazio,
    nao entra — e o diff diz exatamente onde.

E POR QUE E TUDO OU NADA. Declaracao NORMAL nao-camadada vence QUALQUER declaracao camadada,
independentemente da ordem. Entao nao existe migracao parcial com a base de fora: camadar so os
estratos novos faria o `00-v7-base` (178 KB, nao-camadado) vencer todos eles de uma vez. Ou a base
entra na camada mais baixa, ou nao se camada nada.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.painel_css_camadar --aplicar
    PYTHONPATH=. .venv/bin/python -m tools.painel_css_camadar --desfazer
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "static" / "css" / "src"
_CAUDA = _SRC / "99-cauda-important.css"

# prefixo do arquivo -> nome da camada. A ORDEM aqui e a ordem de `@layer`, e ela repete a ordem
# da concatenacao de proposito: camadar nao pode, por si, mudar quem vence.
_CAMADAS = [
    ("00", "base"), ("70", "sobrio"), ("75", "mestras"), ("80", "v54"),
    ("85", "v55"), ("90", "v57"), ("95", "v58"), ("96", "v59"),
]
_MARCA = "/* CAMADADO por tools/painel_css_camadar.py — nao editar esta linha */"


def _blocos(css: str) -> list[str]:
    """Fatia o CSS em blocos de topo, com contagem de chaves e comentario respeitado.

    Comentario ANTES de um bloco viaja COM ele: no painel o comentario e a documentacao da regra,
    e separa-los transformaria o arquivo num amontoado de regras mudas.
    """
    fora: list[str] = []
    buf = ""
    prof = 0
    i, n = 0, len(css)
    while i < n:
        if css[i:i + 2] == "/*":
            f = css.find("*/", i + 2)
            f = n if f < 0 else f + 2
            buf += css[i:f]
            i = f
            continue
        c = css[i]
        buf += c
        if c == "{":
            prof += 1
        elif c == "}":
            prof -= 1
            if prof == 0:
                fora.append(buf)
                buf = ""
        i += 1
    if buf.strip():
        fora.append(buf)
    return fora


def aplicar() -> int:
    if _CAUDA.exists():
        print("[camadar] ja aplicado — rode --desfazer antes", file=sys.stderr)
        return 2
    cauda: list[str] = []
    for pref, nome in _CAMADAS:
        alvos = list(_SRC.glob(f"{pref}-*.css"))
        if not alvos:
            continue
        p = alvos[0]
        css = p.read_text(encoding="utf-8")
        if _MARCA in css:
            print(f"[camadar] {p.name} ja camadado", file=sys.stderr)
            return 2
        dentro, fora = [], []
        for b in _blocos(css):
            sem_com = re.sub(r"/\*.*?\*/", "", b, flags=re.S)
            (fora if "!important" in sem_com else dentro).append(b)
        cauda.extend(fora)
        p.write_text(f"{_MARCA}\n@layer {nome} {{\n" + "".join(dentro) + "\n}\n",
                     encoding="utf-8")
        print(f"[camadar] {p.name}: {len(dentro)} bloco(s) na camada `{nome}`, "
              f"{len(fora)} para a cauda")

    ordem = ", ".join(n for _, n in _CAMADAS)
    cab = (f"{_MARCA}\n"
           "/* A CAUDA NAO-CAMADADA — toda regra com `!important`, na ordem original.\n"
           "   Ler o cabecalho de tools/painel_css_camadar.py antes de tocar: a ordem destes\n"
           "   blocos E o desempate, e mexer nela inverte duelos de `!important` em silencio. */\n")
    _CAUDA.write_text(cab + "".join(cauda), encoding="utf-8")
    # a declaracao de ordem tem de vir ANTES de qualquer `@layer` com corpo
    p0 = list(_SRC.glob("00-*.css"))[0]
    p0.write_text(f"@layer {ordem};\n" + p0.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[camadar] cauda: {len(cauda)} bloco(s) em {_CAUDA.name}")
    print(f"[camadar] ordem declarada: @layer {ordem};")
    print("\nAgora: `painel_css_cortar --juntar`, `painel_bump_versao` e "
          "`painel_computado --comparar`. So entra com diff VAZIO.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args(argv)
    if not a.aplicar:
        ap.error("use --aplicar (o desfazer e `git checkout static/css/src`)")
    return aplicar()


if __name__ == "__main__":
    raise SystemExit(main())
