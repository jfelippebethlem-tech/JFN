#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Descobre TODAS as funções do SIAFE 1 (www5/SiafeRio): loga, varre o DOM do menu ADF, expande cada
módulo e mapeia os itens (funções). Salva a árvore de navegação em data/sei_cache/siafe1_funcoes.json."""
import asyncio, json, os, sys
from pathlib import Path
os.environ["JFN_SIAFE_LOGIN_URL"] = "https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"
sys.path.insert(0, "/home/ubuntu/JFN")
import importlib
import compliance_agent.siafe_ob_orcamentaria as M
importlib.reload(M)
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
              viewport={"width": 1600, "height": 1000},
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            lg = await M._login(pg, 2023)
            print("login SIAFE1:", lg.get("ok"), "| url:", pg.url[:70], flush=True)
            if not lg.get("ok"):
                print("FALHA login:", lg); return
            await pg.wait_for_timeout(3000)
            # 1) menu de topo (ADF: a.xyo / panel menu)
            topo = await pg.evaluate(r"""()=>[...document.querySelectorAll('a.xyo, a[id*="pt_np"], .xyk a, [role=menubar] a')]
                .map(a=>({txt:(a.innerText||'').trim(),id:a.id||'',href:(a.getAttribute('onclick')||a.href||'').slice(0,60)}))
                .filter(o=>o.txt && o.txt.length>1 && o.txt.length<50)""")
            print(f"\n=== MENU DE TOPO ({len(topo)} itens) ===", flush=True)
            for t in topo: print("  ", t["txt"], "|", t["id"][:40], flush=True)
            # 2) expande cada módulo (disclosureAnchor) e captura o FLYOUT real (anchors que ficam VISÍVEIS após o clique)
            topo_txts = {t["txt"] for t in topo}
            arvore = {}
            modulos = [t for t in topo if "disclosureAnchor" in t["id"]]
            for t in modulos:
                try:
                    await pg.evaluate(f"""()=>{{const e=document.getElementById({json.dumps(t['id'])});if(e){{e.click();e.dispatchEvent(new MouseEvent('mouseover',{{bubbles:true}}));}}}}""")
                    await pg.wait_for_timeout(1600)
                    # captura anchors VISÍVEIS (flyout) que não são o menu de topo
                    subs = await pg.evaluate(r"""(topo)=>{
                        const vis=el=>{const r=el.getBoundingClientRect();const s=getComputedStyle(el);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';};
                        const out=[];document.querySelectorAll('a').forEach(a=>{const t=(a.innerText||'').trim();
                          if(t.length>2&&t.length<60&&vis(a)&&!topo.includes(t))out.push({txt:t,id:a.id||''});});
                        return out;}""", list(topo_txts))
                    seen=set(); subs=[s for s in subs if not (s["txt"] in seen or seen.add(s["txt"]))]
                    if subs:
                        arvore[t["txt"]] = subs
                        print(f"\n  ▸ {t['txt']}: {len(subs)} funções", flush=True)
                        for s in subs[:40]: print("      -", s["txt"], flush=True)
                    # fecha o flyout (clica de novo / Esc)
                    await pg.keyboard.press("Escape")
                    await pg.wait_for_timeout(400)
                except Exception as e:
                    print(f"  (erro em {t['txt']}: {str(e)[:60]})", flush=True)
            # 3) dump bruto de TODOS os anchors da página (cobertura total do DOM)
            todos = await pg.evaluate(r"""()=>[...document.querySelectorAll('a')].map(a=>(a.innerText||'').trim()).filter(x=>x.length>2&&x.length<70)""")
            Path("data/sei_cache/siafe1_funcoes.json").write_text(json.dumps(
                {"menu_topo": topo, "arvore": arvore, "todos_anchors": sorted(set(todos))}, ensure_ascii=False, indent=1))
            print(f"\nSALVO siafe1_funcoes.json | {len(arvore)} módulos, {len(set(todos))} anchors únicos", flush=True)
        finally:
            await b.close()


asyncio.run(main())
