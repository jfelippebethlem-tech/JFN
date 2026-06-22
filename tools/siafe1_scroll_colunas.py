#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SIAFE-1: o grid OB Orçamentária VIRTUALIZA colunas (ADF só renderiza as visíveis → peguei 19).
O Processo SEI provavelmente é COLUNA scrollada à direita. Este script rola o grid horizontalmente
em passos e coleta TODOS os headers que aparecem (uniões), + screenshot scale-2 nítido da toolbar.
NUNCA culpar acesso. Salva data/sei_cache/siafe1_scroll_colunas.json. VM-guarded."""
import asyncio, json, os, sys, traceback
from pathlib import Path
os.environ["JFN_SIAFE_LOGIN_URL"] = "https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from tools.vm_guard import preflight, cleanup_orphans
import compliance_agent.siafe_ob_orcamentaria as M
from playwright.async_api import async_playwright
OUT = {"headers_vistos": [], "passos": []}


async def run(ex=2023):
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
                                  viewport={"width": 1920, "height": 1000},
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        vistos = set()
        try:
            for t in range(6):
                lg = await M._login(pg, ex)
                if lg.get("ok"):
                    OUT["passos"].append(f"login_ok_t{t+1}"); break
                await pg.wait_for_timeout(8000)
            else:
                OUT["erro"] = "login (revisar fluxo, NÃO acesso)"; return OUT
            nav = await M._navegar(pg)
            OUT["nav_ok"] = nav.get("ok")
            if not nav.get("ok"):
                OUT["erro"] = "grid não apareceu"; return OUT
            await pg.wait_for_timeout(2000)

            async def colher_headers():
                hs = await pg.evaluate(r"""()=>[...document.querySelectorAll('[id*="tblOBOrcamentaria"] th, [id*="tblOBOrcamentaria"] .af_column_columnHeader')].map(e=>(e.innerText||'').trim()).filter(Boolean)""")
                for h in hs:
                    vistos.add(h)
                return len(hs)

            await colher_headers()
            # rola o container horizontal do grid em passos, re-colhendo headers (ADF lazy-render)
            for i in range(12):
                await pg.evaluate(r"""()=>{
                  const sc=document.querySelector('[id*="tblOBOrcamentaria"] [id*="scroller"], [id*="tblOBOrcamentaria"] .af_table_body, [id*="tblOBOrcamentaria"] div[style*="overflow"]');
                  if(sc){sc.scrollLeft = sc.scrollLeft + 800;}
                  else {const t=document.querySelector('[id*="tblOBOrcamentaria"]'); if(t) t.scrollLeft+=800;}
                }""")
                await pg.wait_for_timeout(1200)
                await colher_headers()
            OUT["headers_vistos"] = sorted(vistos)
            OUT["tem_processo"] = any("rocesso" in h for h in vistos)
            try:
                await pg.screenshot(path=str(REPO / "data/sei_cache/siafe1_scroll.png"))
            except Exception:
                pass
            return OUT
        except Exception:
            OUT["traceback"] = traceback.format_exc()[-1200:]; return OUT
        finally:
            OUT["headers_vistos"] = sorted(vistos)
            (REPO / "data/sei_cache/siafe1_scroll_colunas.json").write_text(json.dumps(OUT, ensure_ascii=False, indent=1), encoding="utf-8")
            await b.close()


if __name__ == "__main__":
    ok, motivo = preflight()
    if not ok:
        print(json.dumps({"ok": False, "vm_guard": motivo})); sys.exit(1)
    cleanup_orphans()
    try:
        print(json.dumps(asyncio.run(run()), ensure_ascii=False)[:500])
    finally:
        cleanup_orphans()
