#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coleta SIAFE 1 (www5) ITERJ(133100) p/ um exercício, salvando HEADER + LINHAS CRUAS em JSON.
Reusa as funções internas de siafe_ob_orcamentaria (login/nav/filtro/colher) — sem ingerir (mapeio depois)."""
import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("JFN_SIAFE_LOGIN_URL", "https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp")
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
import compliance_agent.siafe_ob_orcamentaria as M
from compliance_agent.siafe_adf import AdfSync
from playwright.async_api import async_playwright


async def run(exercicio, ug="133100", maxn=20000):
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
                                  timezone_id="America/Sao_Paulo", viewport={"width": 1600, "height": 1000})
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            lg = await M._login(pg, exercicio)
            if not lg.get("ok"):
                return {"ok": False, "etapa": "login", **lg}
            if not (await M._navegar(pg)).get("ok"):
                return {"ok": False, "etapa": "nav"}
            adf = AdfSync(pg); await adf.boot()
            fr = await M._filtrar_ug(pg, ug)
            if not fr.get("ok"):
                return {"ok": False, "etapa": "filtro", **fr}
            vistos, linhas = set(), []
            header = await M._colher(pg, maxn, vistos, linhas, None)
            out = _REPO / "data" / "sei_cache" / f"siafe1_iterj_{exercicio}.json"
            out.write_text(json.dumps({"exercicio": exercicio, "ug": ug, "header": header,
                                       "n": len(linhas), "linhas": linhas}, ensure_ascii=False), encoding="utf-8")
            return {"ok": True, "exercicio": exercicio, "n": len(linhas), "header": header, "arquivo": str(out)}
        finally:
            await b.close()


if __name__ == "__main__":
    ex = int(sys.argv[1]) if len(sys.argv) > 1 else 2023
    r = asyncio.run(run(ex))
    print(json.dumps({k: v for k, v in r.items() if k != "linhas"}, ensure_ascii=False, indent=1))
