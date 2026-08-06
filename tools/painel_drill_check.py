#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Toda métrica clicável do painel tem de mostrar EXATAMENTE o que ela promete.

O DEFEITO QUE ISTO IMPEDE já apareceu DUAS VEZES no mesmo dia, e as duas por engano meu:

  · na fila de agente público, o KPI dizia **68** comissionados e o clique mostrava **55** — o
    número vinha da fila inteira e o filtro caía sobre os 60 itens que tinham chegado à página;
  · na aba de Riscos, o KPI "Sem cadastro ainda" dizia **647** e a gaveta abria com **0** linhas,
    pela mesma razão.

Nenhum teste unitário pega isso: o JavaScript está certo, a rota está certa, e o erro nasce da
combinação — um número contando o universo e uma lista contendo a página. Só clicando se vê.

MÉTODO: abre o painel de verdade, navega pelas abas, clica em cada `[data-drill]`, lê o valor do
KPI e conta as linhas da gaveta. Diferença = falha. `pageerror` também é falha, porque cartão que
não pinta por boot abortado já enganou esta casa por treze versões.

    python -m tools.painel_drill_check            # todas as abas conhecidas
    python -m tools.painel_drill_check --aba g_riscos
"""
from __future__ import annotations

import argparse
import re
import sys

# As abas que hoje têm métrica clicável. Lista explícita de propósito: varrer todas as abas do
# painel a cada rodada custa minutos numa VM de 2 vCPU, e o que interessa é o que foi convertido.
ABAS = ("g_vinculos", "g_riscos", "e_sanc", "g_hub", "e_poder", "e_conluio",
        "p_comis", "e_adit", "e_escal", "g_prioridade")

# Ação que precisa ser disparada antes de as métricas existirem (aba que só monta sob clique).
PREPARO = {"g_vinculos": '[data-vinc="agentePublico"]'}


def _num(txt: str) -> int | None:
    """'1.234' → 1234. Métrica que não é contagem (percentual, R$) não entra na conferência."""
    t = (txt or "").strip()
    if not re.fullmatch(r"[\d.  ]+", t):
        return None
    d = re.sub(r"\D", "", t)
    return int(d) if d else None


def checar(abas=ABAS, espera_ms: int = 9000) -> dict:
    from playwright.sync_api import sync_playwright

    from tools.painel_boot_check import _BASE, _senha

    achados: list[dict] = []
    erros: list[str] = []
    total = 0
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        pg = b.new_page()
        pg.on("pageerror", lambda e: erros.append(f"pageerror: {e}"))
        pg.on("console", lambda m: erros.append(f"console.error: {m.text}")
              if m.type == "error" else None)
        s = _senha()
        if s:
            pg.goto(f"{_BASE}/login_jfn", wait_until="load")
            pg.fill("input[name=senha]", s)
            pg.press("input[name=senha]", "Enter")
            pg.wait_for_timeout(1200)
        pg.goto(f"{_BASE}/painel", wait_until="load")
        pg.wait_for_timeout(2500)

        for aba in abas:
            pg.evaluate("id => ir(id)", aba)
            pg.wait_for_timeout(3000)
            prep = PREPARO.get(aba)
            if prep and pg.query_selector(prep):
                pg.click(prep)
                pg.wait_for_timeout(espera_ms)
            nomes = pg.evaluate(
                "() => Array.from(document.querySelectorAll('[data-drill]'))"
                ".map(x => x.dataset.drill)")
            for nome in nomes:
                total += 1
                valor = pg.evaluate(
                    "n => {const k=document.querySelector(`[data-drill='${n}']`);"
                    "return k && k.querySelector('.v') ? k.querySelector('.v').innerText : null;}",
                    nome)
                esperado = _num(valor or "")
                pg.click(f'[data-drill="{nome}"]')
                pg.wait_for_timeout(2500)
                # a gaveta genérica conta linhas; a fatia da fila reescreve a própria lista
                visto = pg.evaluate(
                    "() => {const b=document.getElementById('drill-box');"
                    " if (b) return b.querySelectorAll('.grid > .card').length;"
                    " const n=document.body.innerText.match"
                    "(/(\\d[\\d.]*) exibidos de (\\d[\\d.]*) nesta fatia/);"
                    " return n ? parseInt(n[2].replace(/\\D/g,''),10) : null;}")
                if esperado is None:
                    continue
                if visto != esperado:
                    achados.append({"aba": aba, "metrica": nome,
                                    "kpi": esperado, "gaveta": visto})
                pg.evaluate("() => {const b=document.getElementById('drill-box');"
                            " if (b) b.remove();}")
        b.close()
    return {"metricas_clicadas": total, "divergencias": achados, "erros_de_pagina": erros}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aba", action="append", help="limita a uma aba (repetível)")
    a = ap.parse_args()
    r = checar(tuple(a.aba) if a.aba else ABAS)
    print(f"métricas clicadas: {r['metricas_clicadas']}")
    for d in r["divergencias"]:
        print(f"  ✗ {d['aba']}/{d['metrica']}: KPI diz {d['kpi']}, a gaveta mostra {d['gaveta']}")
    for e in r["erros_de_pagina"]:
        print(f"  ✗ {e[:140]}")
    ok = not r["divergencias"] and not r["erros_de_pagina"]
    print("OK — toda métrica mostra o que promete." if ok else "FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
