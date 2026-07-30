#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mede o boot do painel em NÚMEROS — antes de mexer em geometria ou animação.

POR QUE MEDIR ANTES. As três queixas do dono ("fica piscando", "tem uma bola do nada no meio",
"botões sambando") já produziram três hipóteses minhas, e a primeira delas estava ERRADA: eu disse
que `nebulaViva()` vazava elementos `<video>` a cada navegação, e o código reusa
`host.querySelector('video')` — não vaza. Teoria bonita, dado contrário. Então: contar.

O que este script reporta, e por que cada número importa:

  videos            - se cresce com a navegação, há vazamento (a hipótese que eu preciso refutar)
  canvas / rAF      - quantas superfícies animadas competem por 2 vCPU
  animacoes_infinite- `infinite` animando `filter`/`box-shadow` repinta a tela inteira por quadro
  orbe_no_centro    - existe elemento circular no CENTRO da viewport durante a intro? (a "bola")
  nucleo_vs_mascara - distância vertical entre o núcleo do shader e o centro da máscara radial
  fps               - quadros por segundo com a página PARADA
  pageerror         - boot morto (o detector que faltava quando o cockpit ficou 13 versões inerte)

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.painel_medir_boot [--navegacoes 20]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BASE = os.environ.get("JFN_BASE", "http://127.0.0.1:8000")


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


_JS_CENSO = """() => {
  const cs = getComputedStyle(document.documentElement);
  const infinitas = [];
  for (const folha of document.styleSheets) {
    let regras; try { regras = folha.cssRules } catch (e) { continue }
    for (const r of regras || []) {
      const a = r.style && r.style.animation;
      if (a && a.includes('infinite')) infinitas.push({sel: r.selectorText, anim: a});
    }
  }
  // procura elemento circular ocupando o CENTRO da viewport
  const cx = innerWidth / 2, cy = innerHeight / 2, orbes = [];
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) < 0.05) continue;
    const br = s.borderRadius || '';
    if (!(br.includes('50%') || br.includes('9999'))) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 60 || r.height < 60) continue;
    if (Math.abs(r.left + r.width / 2 - cx) < 90 && Math.abs(r.top + r.height / 2 - cy) < 90) {
      orbes.push({id: el.id, cls: el.className && String(el.className).slice(0, 40),
                  w: Math.round(r.width), h: Math.round(r.height),
                  op: s.opacity, z: s.zIndex});
    }
  }
  return {
    videos: document.querySelectorAll('video').length,
    canvas: document.querySelectorAll('canvas').length,
    fixos: [...document.querySelectorAll('body *')].filter(e => getComputedStyle(e).position === 'fixed').length,
    blend: [...document.querySelectorAll('body *')].filter(e => getComputedStyle(e).mixBlendMode !== 'normal').length,
    animacoes_infinite: infinitas.length,
    infinite_com_filter: infinitas.filter(x => /brightness|saturate|blur/.test(x.anim) ||
                                              /tabBreath|sphBreath|nebulaPulse|v18territorio/.test(x.anim)).length,
    orbe_no_centro: orbes,
    abas: (typeof TABS !== 'undefined') ? Object.values(TABS).flat().length : null,
    reduced: cs.getPropertyValue('--reduced') || null,
  };
}"""

_JS_FPS = """() => new Promise(res => {
  let n = 0; const t0 = performance.now();
  const tick = () => { n++; if (performance.now() - t0 < 1000) requestAnimationFrame(tick); else res(n); };
  requestAnimationFrame(tick);
})"""

# Geometria: onde o núcleo do shader cai vs onde a máscara radial abre o buraco.
_JS_GEOM = """() => {
  const el = document.getElementById('pcv');
  if (!el) return null;
  const s = getComputedStyle(el);
  const m = (s.maskImage || s.webkitMaskImage || '') + '';
  const at = m.match(/at\\s+([\\d.]+)%\\s+([\\d.]+)%/);
  return {mask_x: at ? +at[1] : null, mask_y: at ? +at[2] : null, mask_raw: m.slice(0, 120)};
}"""


async def medir(navegacoes: int) -> dict:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright

    erros: list[str] = []
    out: dict = {}
    async with async_playwright() as p:
        nav = await p.chromium.launch(args=["--no-sandbox"])
        pg = await (await nav.new_context(viewport={"width": 1600, "height": 900})).new_page()
        pg.on("pageerror", lambda e: erros.append(f"pageerror: {e}"))
        pg.on("console", lambda m: erros.append(f"console.{m.type}: {m.text}")
              if m.type == "error" else None)

        senha = _senha()
        if senha:
            await pg.goto(f"{_BASE}/login_jfn", wait_until="domcontentloaded")
            try:
                await pg.fill("input[type=password]", senha, timeout=3000)
                await pg.press("input[type=password]", "Enter")
                await pg.wait_for_load_state("domcontentloaded")
            except PlaywrightError as exc:
                # painel sem senha, ou campo ausente: seguir sem login é o comportamento certo —
                # mas o motivo tem de aparecer, senão "não mediu" vira "mediu e estava bom".
                print(f"[medir_boot] login pulado: {exc}", file=__import__("sys").stderr)

        await pg.goto(_BASE, wait_until="domcontentloaded")
        await pg.wait_for_timeout(600)          # dentro da intro de 1,96 s
        out["durante_intro"] = await pg.evaluate(_JS_CENSO)
        out["geometria_mascara"] = await pg.evaluate(_JS_GEOM)
        await pg.wait_for_timeout(2200)         # depois da intro
        out["apos_intro"] = await pg.evaluate(_JS_CENSO)
        out["fps_parado"] = await pg.evaluate(_JS_FPS)

        # navegação repetida: o censo cresce? (teste do vazamento)
        abas = await pg.evaluate("() => (typeof TABS!=='undefined') ? Object.values(TABS).flat() : []")
        for i in range(navegacoes):
            if not abas:
                break
            await pg.evaluate("id => (typeof ir==='function') && ir(id)", abas[i % len(abas)])
            await pg.wait_for_timeout(120)
        out["apos_navegacoes"] = await pg.evaluate(_JS_CENSO)
        out["navegacoes"] = min(navegacoes, len(abas) or 0)
        out["fps_apos_navegar"] = await pg.evaluate(_JS_FPS)
        await nav.close()

    out["erros"] = erros
    a, d = out["apos_intro"], out["apos_navegacoes"]
    out["veredito"] = {
        "vazamento_video": d["videos"] - a["videos"],
        "vazamento_canvas": d["canvas"] - a["canvas"],
        "orbe_durante_intro": len(out["durante_intro"]["orbe_no_centro"]),
        "boot_morto": bool([e for e in erros if e.startswith("pageerror")]),
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--navegacoes", type=int, default=20)
    a = ap.parse_args()
    print(json.dumps(asyncio.run(medir(a.navegacoes)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
