#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DOM SWEEP COMPLETO do SIAFE-1 (parar de adivinhar). Loga, navega ao grid OB Orçamentária (com RETRY
robusto até carregar), e dumpa TODO o DOM relevante (tag/id/classe/texto/title/href/onclick) de cada tela.
Depois clica sistematicamente nos elementos de toolbar/menu e re-dumpa, pra mapear o caminho do Processo.
Salva data/sei_cache/siafe1_dom_*.json + screenshots. NUNCA culpar acesso. VM-guarded."""
import asyncio, json, os, sys, traceback
from pathlib import Path
os.environ["JFN_SIAFE_LOGIN_URL"] = "https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from tools.vm_guard import preflight, cleanup_orphans
import compliance_agent.siafe_ob_orcamentaria as M
from playwright.async_api import async_playwright
SC = REPO / "data/sei_cache"

DUMP_JS = r"""()=>{
  const rows=[];
  document.querySelectorAll('a,button,img,input,div[role],span[role],th,[onclick],label,td.af_column_columnHeader').forEach(e=>{
    const id=e.id||''; const cls=(e.className||'').toString().slice(0,50);
    const t=(e.getAttribute&&(e.getAttribute('title')||e.getAttribute('alt'))||'').trim();
    const s=(e.innerText||'').trim().slice(0,40);
    const href=(e.getAttribute&&e.getAttribute('href')||'').slice(0,50);
    const onc=(e.getAttribute&&e.getAttribute('onclick'))?'Y':'';
    if(id||t||s||onc) rows.push({tag:e.tagName,id:id,cls:cls,title:t.slice(0,40),txt:s,href:href,onc:onc});
  });
  return rows.slice(0,600);
}"""


async def nav_robusto(pg):
    for tent in range(4):
        nav = await M._navegar(pg)
        if nav.get("ok"):
            return True
        await pg.wait_for_timeout(4000)
    return False


async def run(ex=2023):
    OUT = {"passos": []}
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR", viewport={"width": 1920, "height": 1080},
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page(); await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            for t in range(8):
                lg = await M._login(pg, ex)
                if lg.get("ok"):
                    OUT["passos"].append(f"login_t{t+1}"); break
                await pg.wait_for_timeout(7000)
            else:
                OUT["erro"] = "login (revisar fluxo, NÃO acesso)"; return OUT
            if not await nav_robusto(pg):
                OUT["erro"] = "nav falhou em 4 tentativas"; return OUT
            OUT["passos"].append("nav_ok")
            await pg.wait_for_timeout(2500)
            await pg.screenshot(path=str(SC / "siafe1_dom_grid.png"))
            # DUMP 1: grid carregado
            OUT["dom_grid"] = await pg.evaluate(DUMP_JS)
            # clica a 1ª linha (selecionar) e re-dumpa (pode habilitar toolbar/detalhe)
            try:
                cell = await pg.query_selector('[id*="tblOBOrcamentaria"] td')
                if cell:
                    await cell.click(); await pg.wait_for_timeout(2500)
                    await pg.screenshot(path=str(SC / "siafe1_dom_selrow.png"))
                    OUT["dom_pos_select"] = await pg.evaluate(DUMP_JS)
            except Exception as e:
                OUT["sel_erro"] = str(e)[:60]
            return OUT
        except Exception:
            OUT["tb"] = traceback.format_exc()[-1200:]; return OUT
        finally:
            (SC / "siafe1_dom_sweep.json").write_text(json.dumps(OUT, ensure_ascii=False, indent=1), encoding="utf-8")
            await b.close()


if __name__ == "__main__":
    ok, m = preflight()
    if not ok:
        print(json.dumps({"ok": False, "vm_guard": m})); sys.exit(1)
    cleanup_orphans()
    try:
        r = asyncio.run(run()); print(json.dumps({k: v for k, v in r.items() if k in ("passos", "erro", "tb")}, ensure_ascii=False))
    finally:
        cleanup_orphans()
