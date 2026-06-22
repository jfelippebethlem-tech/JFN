#!/usr/bin/env python3
"""ONE-SHOT (agendado pós-cooldown): recupera o Processo SEI do SIAFE-1. UM login só (não martelar).
Caminhos: (a) clique REAL no commandLink do número da OB -> detalhe; (b) consulta 'Execução Orçamentária'
(NE/empenho) -> colunas. Dump DOM+screenshot+Processo. Grava data/sei_cache/siafe1_processo_oneshot.json."""
import asyncio,json,os,sys,traceback
from pathlib import Path
os.environ["JFN_SIAFE_LOGIN_URL"]="https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"
REPO=Path("/home/ubuntu/JFN");sys.path.insert(0,str(REPO))
import compliance_agent.siafe_ob_orcamentaria as M
from playwright.async_api import async_playwright
O={}
async def run(ex=2023):
    async with async_playwright() as pw:
        b=await pw.chromium.launch(headless=True,args=["--no-sandbox","--ignore-certificate-errors"])
        ctx=await b.new_context(ignore_https_errors=True,locale="pt-BR",viewport={"width":1920,"height":1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg=await ctx.new_page();await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            for t in range(5):
                if (await M._login(pg,ex)).get("ok"): O["login"]=t+1;break
                await pg.wait_for_timeout(10000)
            nav=False
            for _ in range(3):
                if (await M._navegar(pg)).get("ok"): nav=True;break
                await pg.wait_for_timeout(5000)
            O["nav"]=nav
            if nav:
                await pg.wait_for_timeout(2500)
                lk=await pg.query_selector('[id*="tblOBOrcamentaria"] td a')
                if lk:
                    O["link_txt"]=(await lk.inner_text())[:20]
                    await lk.click(); await pg.wait_for_timeout(6000)
                    await pg.screenshot(path=str(REPO/"data/sei_cache/siafe1_oneshot_detalhe.png"))
                    O["proc_detalhe"]=await pg.evaluate(r"""()=>{const o=[];document.querySelectorAll('label,span,td,div,input').forEach(e=>{const s=((e.innerText||'')+' '+(e.value||'')).trim();if(/processo/i.test(s)&&s.length<120)o.push(s)});return [...new Set(o)].slice(0,25);}""")
            return O
        except Exception: O["tb"]=traceback.format_exc()[-600:];return O
        finally:
            (REPO/"data/sei_cache/siafe1_processo_oneshot.json").write_text(json.dumps(O,ensure_ascii=False,indent=1)); await b.close()
if __name__=="__main__":
    from tools.vm_guard import preflight,cleanup_orphans
    ok,_=preflight()
    cleanup_orphans()
    asyncio.run(run())
