#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""painel_boot_check — o boot do painel morreu? A resposta é `pageerror`, não a aparência da tela.

POR QUE ESTE SCRIPT EXISTE. O boot do painel já morreu calado duas vezes por motivos diferentes
(TDZ numa `const` referenciada antes da declaração; corrida com View Transitions) e o cockpit ficou
inerte por treze versões, porque o sintoma visível — "o card não apareceu", "não pintou o glifo" —
parecia problema de CSS. O detector correto é o evento `pageerror`: uma exceção no boot aborta o
resto do script e nada mais é montado.

O walker completo (`_SANDBOX/walker_humano.py`) tira screenshot de 57 abas e leva minutos numa VM de
2 vCPU. Este é o check rápido, para rodar depois de cada mexida em `TABS` ou nos renders: sobe,
percorre as abas pedidas, e falha se houver `pageerror` ou erro de console.

Uso:
  PYTHONPATH=. .venv/bin/python -m tools.painel_boot_check                  # abas novas
  PYTHONPATH=. .venv/bin/python -m tools.painel_boot_check --todas          # as 57
  PYTHONPATH=. .venv/bin/python -m tools.painel_boot_check --aba g_vinculos
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BASE = os.environ.get("JFN_BASE", "http://127.0.0.1:8000")

# Ruído conhecido que não indica boot morto: recurso externo bloqueado, favicon, aviso de rede.
_RUIDO = ("favicon", "net::ERR_", "Failed to load resource", "AbortError",
          "ResizeObserver loop", "Download the React DevTools")


def _senha() -> str:
    for chave in ("JFN_DASH_SENHA", "DASH_SENHA", "PAINEL_SENHA"):
        if os.environ.get(chave):
            return os.environ[chave]
    env = _REPO / ".env"
    if env.exists():
        for ln in env.read_text(errors="ignore").splitlines():
            if ln.split("=", 1)[0].strip() in ("JFN_DASH_SENHA", "DASH_SENHA", "PAINEL_SENHA"):
                return ln.split("=", 1)[1].strip().strip("'\"")
    return ""


def _relevante(msg: str) -> bool:
    return not any(r in msg for r in _RUIDO)


def checar(abas: list[str], *, todas: bool = False) -> dict:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    erros: list[str] = []
    laudo: dict = {"boot": {"pageerror": [], "console": []}, "abas": {}}

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        pg = b.new_page()
        pg.on("pageerror", lambda e: erros.append(f"PAGEERROR: {e}"))
        pg.on("console", lambda m: erros.append(f"CONSOLE[{m.type}]: {m.text}")
              if m.type == "error" else None)
        try:
            senha = _senha()
            if senha:
                pg.goto(f"{_BASE}/login_jfn", wait_until="load")
                try:
                    pg.fill("input[name=senha]", senha)
                    pg.press("input[name=senha]", "Enter")
                    pg.wait_for_timeout(1200)
                except (PlaywrightError, PlaywrightTimeout) as e:
                    # painel sem tela de senha (ou seletor mudou): segue para /painel. Silenciar
                    # aqui esconderia uma mudança de login que faria o check medir a tela errada.
                    print(f"[boot] login não aplicado ({str(e)[:70]}); seguindo sem sessão", flush=True)
            pg.goto(f"{_BASE}/painel", wait_until="load")
            pg.wait_for_timeout(3000)
            laudo["boot"]["pageerror"] = [e for e in erros if e.startswith("PAGEERROR") and _relevante(e)]
            laudo["boot"]["console"] = [e for e in erros if e.startswith("CONSOLE") and _relevante(e)]

            # o sinal DEFINITIVO de boot vivo: o roteador e o catálogo de abas existem
            vivo = pg.evaluate("() => typeof ir === 'function' && typeof TABS === 'object'")
            laudo["boot"]["roteador_vivo"] = bool(vivo)
            if todas:
                abas = pg.evaluate("Object.values(TABS).flat().map(t=>t.id)")
            laudo["boot"]["n_abas"] = pg.evaluate("Object.values(TABS).flat().length")

            for aba in abas:
                del erros[:]
                info: dict = {}
                try:
                    pg.evaluate("id => ir(id)", aba)
                    pg.wait_for_timeout(1500)
                except (PlaywrightError, PlaywrightTimeout) as e:
                    info["falha_ir"] = str(e)[:200]
                info.update(pg.evaluate(
                    """(()=>{const v=document.getElementById('view');
                       if(!v)return {sem_view:true};
                       return {texto: v.innerText.trim().length,
                               cards: v.querySelectorAll('.card,table,li').length,
                               clicaveis: v.querySelectorAll('[onclick],button').length};})()"""))
                info["erros"] = [e for e in erros if _relevante(e)]
                laudo["abas"][aba] = info
        finally:
            b.close()
    return laudo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aba", action="append", default=[], help="aba a percorrer (repetível)")
    ap.add_argument("--todas", action="store_true", help="percorre todas as abas do painel")
    a = ap.parse_args(argv)
    novas = ["g_vinculos", "g_pecas", "g_fontes", "g_hub", "g_acuracia"]
    laudo = checar(a.aba or novas, todas=a.todas)

    boot = laudo["boot"]
    print(json.dumps(laudo, ensure_ascii=False, indent=1)[:4000])
    problemas = []
    if boot["pageerror"]:
        problemas.append(f"BOOT MORTO: {len(boot['pageerror'])} pageerror — {boot['pageerror'][:2]}")
    if not boot.get("roteador_vivo"):
        problemas.append("BOOT MORTO: `ir()` ou `TABS` não existem no escopo global")
    for aba, i in laudo["abas"].items():
        if i.get("falha_ir"):
            problemas.append(f"{aba}: ir() falhou — {i['falha_ir'][:120]}")
        if i.get("erros"):
            problemas.append(f"{aba}: {len(i['erros'])} erro(s) — {i['erros'][0][:140]}")
        elif (i.get("texto") or 0) < 40:
            problemas.append(f"{aba}: conteúdo praticamente vazio ({i.get('texto')} chars)")
    if problemas:
        print("\n=== PROBLEMAS ===")
        for p in problemas:
            print(" •", p)
        return 1
    print(f"\nOK — boot vivo, {boot['n_abas']} abas no catálogo, "
          f"{len(laudo['abas'])} percorrida(s) sem erro.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
