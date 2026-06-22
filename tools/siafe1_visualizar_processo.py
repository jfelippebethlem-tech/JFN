#!/usr/bin/env python3
"""SIAFE-1: recupera o Processo SEI via caminho CONFIRMADO — selecionar linha do grid OB → clicar
'Visualizar' (link x12k) → detalhe da OB com o campo Processo. UM login só (não martelar; SIAFE-1 throttla
por burst → ~1 nav limpo por cooldown). Grava data/sei_cache/siafe1_visualizar.json + screenshot."""
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
                await pg.wait_for_timeout(9000)
            nav=False
            for _ in range(3):
                if (await M._navegar(pg)).get("ok"): nav=True;break
                await pg.wait_for_timeout(5000)
            O["nav"]=nav
            if not nav: return O
            await pg.wait_for_timeout(2500)
            await pg.evaluate(r"""()=>{const c=document.querySelector('[id*="tblOBOrcamentaria"] tbody td, [id*="tblOBOrcamentaria"] td');if(c)c.click();}""")
            await pg.wait_for_timeout(1800)
            O["visualizar"]=await pg.evaluate(r"""()=>{const a=[...document.querySelectorAll('a')].find(e=>/^visualizar$/i.test((e.innerText||'').trim()));if(a){a.click();return 'ok';}return 'sem';}""")
            await pg.wait_for_timeout(6000)
            await pg.screenshot(path=str(REPO/"data/sei_cache/siafe1_visualizar.png"))
            O["proc"]=await pg.evaluate(r"""()=>{const o=[];document.querySelectorAll('label,span,td,div,input').forEach(e=>{const s=((e.innerText||'')+' '+(e.value||'')).trim();if(/processo/i.test(s)&&s.length<140)o.push(s)});return [...new Set(o)].slice(0,25);}""")
            O["labels"]=await pg.evaluate(r"""()=>[...new Set([...document.querySelectorAll('label,.af_panelLabelAndMessage_label')].map(e=>(e.innerText||'').trim()).filter(t=>t&&t.length<45))].slice(0,90)""")
            return O
        except Exception: O["tb"]=traceback.format_exc()[-600:];return O
        finally:
            (REPO/"data/sei_cache/siafe1_visualizar.json").write_text(json.dumps(O,ensure_ascii=False,indent=1));await b.close()
if __name__=="__main__":
    from tools.vm_guard import cleanup_orphans
    cleanup_orphans()
    asyncio.run(run())
    print(json.dumps(O,ensure_ascii=False)[:400])
