#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""painel_clique_check — o painel RECEBE clique. Nao "tem botao": RECEBE clique.

POR QUE ESTE ARQUIVO EXISTE, e a resposta e uma falha de dois meses.

O deck da Consciencia (v58) declara `display:flex`. Uma declaracao de `display` VENCE o
`[hidden]{display:none}` da folha do navegador — entao o `d.hidden = true` que o codigo executava
nao escondia coisa nenhuma. O deck ficava permanentemente no layout: `position:fixed`, `inset:0`,
`z-index:60`, invisivel a `opacity:0`, com `pointer-events` ligado. Um escudo de tela cheia por
cima do painel inteiro.

O PAINEL FICOU SEM RECEBER UM CLIQUE desde entao. E as redes que existiam diziam que estava tudo
bem, porque nenhuma delas clica:

  · `painel_boot_check --todas` navega chamando `ir('e_sobre')` por JavaScript. Para ele: 60 abas,
    zero pageerror, sobre uma tela que nao respondia ao mouse.
  · as sondas de tela contavam `document.querySelectorAll('button').length` — 44 botoes! — e
    `querySelectorAll` enxerga o que esta DEBAIXO de um escudo tao bem quanto o que esta em cima.
  · `auditar_layout` mede geometria, e a geometria estava correta.

Quem achou foi o dono, dizendo "nao consigo clicar em nada".

A LICAO, e ela e maior que o bug: **uma suite que so exercita o caminho programatico mede o
caminho programatico.** `ir()` funcionando nao e o painel funcionando; o painel funcionando e o
dedo do auditor chegando ao dado. Toda vez que uma verificacao troca o gesto real por uma chamada
de funcao — mais rapida, mais estavel, mais facil de escrever — ela deixa de medir a unica coisa
que interessa.

O QUE ELE FAZ, e e deliberadamente burro:

 1. `elementFromPoint` no CENTRO de cada controle. Se quem responde ali nao e o controle (nem um
    descendente dele), ha algo por cima — e o laudo diz O QUE, com id e classe.
 2. Um clique de VERDADE (`page.click`, que recusa elemento coberto) numa esfera, e a confirmacao
    de que a esfera mudou. E o gesto mais basico do painel: trocar de contexto.
 3. Inventario de todo elemento `fixed`/`absolute` que cobre >=90% da viewport SEM
    `pointer-events:none`. E a assinatura da familia inteira de bugs, nao so deste caso.

Uso:
    JFN_BASE=http://127.0.0.1:8000 PYTHONPATH=. .venv/bin/python -m tools.painel_clique_check
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

BASE = os.environ.get("JFN_BASE", "http://127.0.0.1:8000")

# Os controles que precisam responder. Sao os quatro gestos sem os quais o painel nao e um painel:
# trocar de esfera, trocar de aba, abrir um KPI e alcancar o cabecalho.
_ALVOS = [
    ("esfera", ".spheres .sph, .sph"),
    ("aba", "nav.tabs button"),
    ("cartao", "#view .card, #view .ck-inst"),
    ("cabecalho", ".htop a, header a, header button"),
]

_SONDA = r"""(alvos => {
  const cs = e => getComputedStyle(e);
  const nome = e => !e ? 'null'
    : e.tagName.toLowerCase() + (e.id ? '#' + e.id : '')
      + (typeof e.className === 'string' && e.className
         ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : '');

  const laudo = {controles: [], escudos: []};

  for (const [rotulo, sel] of alvos) {
    const el = document.querySelector(sel);
    if (!el) { laudo.controles.push({rotulo, achado: false}); continue; }
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) {
      laudo.controles.push({rotulo, achado: true, semArea: true}); continue;
    }
    const x = Math.round(r.left + r.width / 2), y = Math.round(r.top + r.height / 2);
    /* Ponto FORA da janela nao e testavel: `elementFromPoint` devolve null e isso nao diz nada
       sobre escudo nenhum. Em 390px o primeiro cartao ja nasce abaixo da dobra. Rolar ate ele
       seria uma medida melhor e um teste mais lento; aqui basta nao mentir. */
    if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) {
      laudo.controles.push({rotulo, achado: true, foraDaDobra: true, ponto: [x, y]});
      continue;
    }
    const topo = document.elementFromPoint(x, y);
    // vale se quem responde E o controle, ou algo DENTRO dele (um <span> do rotulo, por exemplo)
    const ok = !!topo && (topo === el || el.contains(topo) || topo.contains(el));
    laudo.controles.push({rotulo, achado: true, ok, alvo: nome(el), responde: nome(topo),
                          ponto: [x, y]});
  }

  /* A ASSINATURA DA FAMILIA: qualquer coisa posicionada que cubra a tela e continue recebendo
     ponteiro. Nao importa se e invisivel — `opacity:0` nao desliga clique, e foi exatamente
     assim que este bug se escondeu. */
  for (const e of document.querySelectorAll('body *')) {
    const s = cs(e);
    if (s.pointerEvents === 'none' || s.display === 'none' || s.visibility === 'hidden') continue;
    if (s.position !== 'fixed' && s.position !== 'absolute') continue;
    const b = e.getBoundingClientRect();
    if (b.width >= innerWidth * 0.9 && b.height >= innerHeight * 0.9) {
      laudo.escudos.push({el: nome(e), z: s.zIndex, opacidade: s.opacity, pos: s.position});
    }
  }
  return laudo;
})"""


async def _rodar(larguras: list[int]) -> dict:
    from playwright.async_api import async_playwright

    fora: dict = {}
    async with async_playwright() as p:
        nav = await p.chromium.launch(args=["--no-sandbox"])
        pg = await nav.new_page(viewport={"width": larguras[0], "height": 900})
        erros: list[str] = []
        pg.on("pageerror", lambda e: erros.append(str(e)))
        await pg.goto(f"{BASE}/painel", wait_until="load")
        await pg.wait_for_timeout(2000)
        if "login" in pg.url:
            fora["_login"] = "servidor pede login — rode contra o loopback, que nao pede"
        # ESPERA O PORTAL SAIR — ele cobre a tela DE PROPOSITO por ~2 s e se remove sozinho.
        # Medir antes disso acusa um escudo que e a abertura, e um detector que acusa a abertura
        # some do uso na primeira semana. Medido: a 1,5 s e a 3 s nada responde ao ponteiro; a
        # partir de ~6 s tudo responde.
        try:
            await pg.wait_for_function(
                "() => !document.getElementById('portal')"
                " || getComputedStyle(document.getElementById('portal')).display === 'none'",
                timeout=12000)
        except Exception as e:                                  # noqa: BLE001
            # Portal que nao sai em 12 s E um achado, nao um detalhe: ele cobre a viewport de
            # propósito, e preso ele e o proprio escudo que este arquivo existe para pegar.
            print(f"[clique] o portal nao saiu em 12 s: {e!s:.70}", file=sys.stderr)
        await pg.wait_for_timeout(3500)

        for larg in larguras:
            await pg.set_viewport_size({"width": larg, "height": 900})
            await pg.wait_for_timeout(900)
            fora[str(larg)] = await pg.evaluate(_SONDA, _ALVOS)

        # ── o gesto de verdade ──────────────────────────────────────────────────────────────
        await pg.set_viewport_size({"width": larguras[0], "height": 900})
        await pg.wait_for_timeout(600)
        antes = await pg.evaluate("() => (typeof esfera !== 'undefined') ? esfera : null")
        try:
            # `.sph:nth-child(2)` era um seletor ERRADO — `.sph` nao e o 2o filho do container.
            # `nth(1)` conta entre os `.sph`, que e o que se quer dizer.
            await pg.locator(".sph").nth(1).click(timeout=8000)
            await pg.wait_for_timeout(2500)
            depois = await pg.evaluate("() => (typeof esfera !== 'undefined') ? esfera : null")
            fora["_gesto"] = {"ok": antes != depois, "de": antes, "para": depois}
        except Exception as e:                                  # noqa: BLE001
            fora["_gesto"] = {"ok": False, "de": antes, "erro": str(e).split("\n")[0][:160]}

        fora["_pageerror"] = erros
        await nav.close()
    return fora


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--larguras", default="1440,390")
    a = ap.parse_args(argv)
    larguras = [int(x) for x in a.larguras.split(",")]

    laudo = asyncio.run(_rodar(larguras))
    if a.json:
        print(json.dumps(laudo, ensure_ascii=False, indent=1))

    problemas: list[str] = []
    for larg in larguras:
        d = laudo.get(str(larg)) or {}
        for c in d.get("controles", []):
            if not c.get("achado") or c.get("semArea") or c.get("foraDaDobra"):
                continue                     # nao existe / sem area / fora da janela: nao e falha
            if not c.get("ok"):
                problemas.append(
                    f"{larg}px · o clique em `{c['rotulo']}` ({c['alvo']}) nao chega: quem responde "
                    f"no ponto {c['ponto']} e `{c['responde']}`")
        for e in d.get("escudos", []):
            problemas.append(
                f"{larg}px · `{e['el']}` cobre a viewport (z={e['z']}, opacidade={e['opacidade']}, "
                f"{e['pos']}) e RECEBE ponteiro — `opacity:0` nao desliga clique")

    g = laudo.get("_gesto") or {}
    if not g.get("ok"):
        problemas.append(f"o gesto real falhou: clicar numa esfera nao trocou de contexto ({g})")

    if laudo.get("_pageerror"):
        problemas.append(f"pageerror: {laudo['_pageerror'][:3]}")

    if problemas:
        print("=== O PAINEL NAO RECEBE CLIQUE ===")
        for p in problemas:
            print(f"  • {p}")
        print("\nLer o cabecalho deste arquivo: `querySelectorAll('button').length` conta botoes")
        print("debaixo de um escudo tao bem quanto botoes em cima. Contar nao e clicar.")
        return 1
    print(f"OK — o clique chega em todos os controles, em {larguras} px, e o gesto real responde.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
