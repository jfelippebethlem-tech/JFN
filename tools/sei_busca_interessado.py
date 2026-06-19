#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Busca SEI por INTERESSADO (pesquisa avançada) — acha o processo da contratação/aditivos da MGS no ITERJ.
Modo 'inspect' dumpa os campos do form; modo 'buscar <termo>' preenche Interessado/Especificação e lista resultados."""
import asyncio, sys, re, json
sys.path.insert(0, "/home/ubuntu/JFN")
from tools import sei_reader as SR

MODO = sys.argv[1] if len(sys.argv) > 1 else "inspect"
TERMO = sys.argv[2] if len(sys.argv) > 2 else "MGS CLEAN"


async def main():
    from compliance_agent.recursos import browser_lock_async
    from playwright.async_api import async_playwright
    async with browser_lock_async(espera_max=300), async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            if not await SR.login(pg, tentativas=30):
                print("LOGIN FALHOU"); return
            print("login OK; abrindo pesquisa…", flush=True)
            # menu Pesquisa
            await pg.evaluate(r"""()=>{const e=[...document.querySelectorAll('a')].find(a=>/^pesquisa$/i.test((a.innerText||'').trim())||/protocolo_pesquisar\b/i.test(a.href||a.getAttribute('onclick')||''));if(e)e.click();}""")
            await pg.wait_for_timeout(5000)
            if MODO == "inspect":
                campos = await pg.evaluate(r"""()=>{
                  const out=[];
                  document.querySelectorAll('input,select,textarea').forEach(e=>{
                    if(e.type==='hidden')return;
                    out.push({tag:e.tagName,id:e.id||'',name:e.name||'',type:e.type||'',ph:e.placeholder||'',
                              label:(e.labels&&e.labels[0]?e.labels[0].innerText:'').slice(0,40)});
                  });return out;}""")
                for c in campos:
                    print("  ", {k: v for k, v in c.items() if v})
            else:
                # tenta preencher o campo Interessado (autocomplete) e/ou Especificação
                done = await pg.evaluate(r"""(t)=>{
                  const cands=[...document.querySelectorAll('input[type=text]')];
                  const find=lbl=>cands.find(e=>{const L=((e.labels&&e.labels[0]?e.labels[0].innerText:'')+' '+(e.id||'')+' '+(e.name||'')).toLowerCase();return lbl.test(L);});
                  let hit=[];
                  const inter=find(/interess/); if(inter){inter.value=t;inter.dispatchEvent(new Event('input',{bubbles:true}));hit.push('interessado');}
                  const espec=find(/especif|descri/); if(espec){espec.value=t;espec.dispatchEvent(new Event('input',{bubbles:true}));hit.push('espec');}
                  return hit;}""", TERMO)
                print("preenchido:", done, flush=True)
                await pg.wait_for_timeout(2500)
                # submeter
                await pg.evaluate(r"""()=>{const b=document.querySelector('#sbmPesquisar,#btnPesquisar')||[...document.querySelectorAll('button,input[type=submit]')].find(e=>/pesquisar/i.test(e.value||e.innerText||''));if(b)b.click();}""")
                await pg.wait_for_timeout(6000)
                txt = await pg.inner_text("body")
                procs = sorted(set(re.findall(r"SEI[- ]?\d{6}/\d{6}/\d{4}", txt)))
                print(f"\nPROCESSOS encontrados ({len(procs)}):")
                for p in procs[:40]:
                    print("  ", p)
        finally:
            await b.close()


asyncio.run(main())
