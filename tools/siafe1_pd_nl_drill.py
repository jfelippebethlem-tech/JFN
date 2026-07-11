#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Drill SIAFE 1: abre 'Execução Financeira > Acompanhamento de Execução de PD', filtra por um PD
e extrai a Nota de Liquidação (NL) que ele paga. 1ª rodada = DISCOVERY da página (campos do form +
conteúdo), p/ localizar onde o NL aparece. VM-guarded. Playwright local (SIAFE é ADF autenticado)."""
import asyncio
import json
import os
import sys
from pathlib import Path

os.environ["JFN_SIAFE_LOGIN_URL"] = "https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from tools.vm_guard import preflight, cleanup_orphans
import compliance_agent.siafe_ob_orcamentaria as M
from playwright.async_api import async_playwright

PD_TESTE = "2022PD00914"   # OB00846 (par de valor R$93.041,16) — alvo de discovery
MENU_ID = "pt1:pt_np2:0:pt_cni3"  # Acompanhamento de Execução de PD


async def run(pd_alvo=PD_TESTE, ex=2022):
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
                                  timezone_id="America/Sao_Paulo", viewport={"width": 1600, "height": 1000})
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            lg = await M._login(pg, ex)
            if not lg.get("ok"):
                return {"ok": False, "etapa": "login", **lg}
            await pg.evaluate(r"""()=>{const a=[...document.querySelectorAll('a.xyo,a')].find(e=>(e.innerText||'').trim()==='Execução');if(a)a.click();}""")
            await pg.wait_for_timeout(1500)
            await pg.evaluate(r"""()=>{const a=[...document.querySelectorAll('a.xyo,a')].find(e=>(e.innerText||'').trim()==='Execução Financeira');if(a)a.click();}""")
            await pg.wait_for_timeout(1500)
            # clica 'Acompanhamento de Execução de PD' (por id, fallback por texto)
            clicked = await pg.evaluate(r"""(mid)=>{let el=document.getElementById(mid);
                if(!el)el=[...document.querySelectorAll('a')].find(e=>(e.innerText||'').trim()==='Acompanhamento de Execução de PD');
                if(el){el.click();return true;}return false;}""", MENU_ID)
            await pg.wait_for_timeout(2500)
            # 1) digita o PD no campo de consulta e pesquisa (Enter)
            try:
                await pg.fill('[id="pt1:iTxtCad::content"]', pd_alvo, timeout=6000)
            except Exception:
                await pg.evaluate(r"""(v)=>{const e=document.getElementById('pt1:iTxtCad::content');if(e){e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}));}}""", pd_alvo)
            await pg.keyboard.press("Enter")
            await pg.wait_for_timeout(3500)
            # 2) extrai NL/NE/OB + texto do resultado
            res = await pg.evaluate(r"""()=>{
                const t=document.body.innerText||'';
                const grab=(re)=>[...new Set((t.match(re)||[]))].slice(0,12);
                // linhas de tabela (árvore de execução do PD)
                const rows=[...document.querySelectorAll('tr')].map(r=>(r.innerText||'').replace(/\s+/g,' ').trim()).filter(x=>x && /NL|NE|OB|Liquid|Empenh/i.test(x)).slice(0,25);
                return {NL: grab(/\d{4}NL\d+/g), NE: grab(/\d{4}NE\d+/g), OB: grab(/\d{4}OB\d+/g),
                        liquid_kw: grab(/(Nota de Liquidação|Liquidação|Documento Hábil)/gi),
                        linhas: rows, trecho: t.slice(0,500)};
            }""")
            out = REPO / "data/sei_cache/siafe1_pd_nl_resultado.json"
            out.write_text(json.dumps({"ok": True, "pd_alvo": pd_alvo, "menu_clicked": clicked, "resultado": res},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
            return {"ok": True, "pd_alvo": pd_alvo, "NL": res.get("NL"), "NE": res.get("NE"),
                    "OB": res.get("OB"), "liquid_kw": res.get("liquid_kw"),
                    "n_linhas": len(res.get("linhas", [])), "arquivo": str(out)}
        finally:
            await b.close()


if __name__ == "__main__":
    ok, motivo = preflight()
    if not ok:
        print(json.dumps({"ok": False, "vm_guard": motivo}, ensure_ascii=False)); sys.exit(1)
    cleanup_orphans()
    try:
        print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=1))
    finally:
        cleanup_orphans()
