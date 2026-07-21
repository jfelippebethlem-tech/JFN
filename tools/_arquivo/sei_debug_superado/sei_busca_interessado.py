#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Busca SEI por INTERESSADO (pesquisa avançada) — acha o processo da contratação/aditivos da MGS no ITERJ.
Modo 'inspect' dumpa os campos do form; modo 'buscar <termo>' preenche Interessado/Especificação e lista resultados."""
import asyncio
import sys
import re
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
                # BUSCA POR INTERESSADO = campo 'Contato' (txtContato, autocomplete cadastrado) + Considerar Documentos.
                done = await pg.evaluate(r"""(t)=>{
                  let hit=[];
                  const rp=document.getElementById('optProcessos'); if(rp&&!rp.checked){try{rp.click();hit.push('radio:processos')}catch(e){}}
                  const cd=document.getElementById('chkSinConsiderarDocumentos'); if(cd&&!cd.checked){try{cd.click();hit.push('considerarDocs')}catch(e){}}
                  const so=document.getElementById('selOrgaoPesquisa'); if(so){[...so.options].forEach(o=>o.selected=false);so.dispatchEvent(new Event('change',{bubbles:true}));hit.push('orgao:limpo');}
                  const c=document.getElementById('txtContato');
                  if(c){c.value=t;c.focus();c.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true}));c.dispatchEvent(new Event('input',{bubbles:true}));c.dispatchEvent(new Event('keyup',{bubbles:true}));hit.push('contato:txtContato');}
                  return hit;}""", TERMO)
                # espera o autocomplete do Contato e seleciona a opção da MGS
                await pg.wait_for_timeout(3500)
                sel = await pg.evaluate(r"""(t)=>{
                  const T=t.toUpperCase().split(' ')[0];
                  // dropdowns de autocomplete do SEI (div/li/a com o nome do contato)
                  const op=[...document.querySelectorAll('div.ajax_result a, li, a, div')].find(e=>{const s=(e.innerText||'').toUpperCase();return s.includes(T)&&s.length<120&&(s.includes('MGS')||s.includes('19.088')||s.includes('19088'));});
                  if(op){op.click();return (op.innerText||'').trim().slice(0,80);} return 'sem opção autocomplete';}""", TERMO)
                print("contato selecionado:", sel, flush=True)
                # fallback: se autocomplete não veio, usa também o full-text 'q'
                if "sem opção" in sel:
                    await pg.evaluate(r"""(t)=>{const q=document.getElementById('q');if(q){q.value=t;q.dispatchEvent(new Event('input',{bubbles:true}));}}""", TERMO)
                print("preenchido:", done, flush=True)
                await pg.wait_for_timeout(1500)
                # submit robusto (botão por id/valor; form submit; Enter)
                await pg.evaluate(r"""()=>{const b=document.querySelector('#sbmPesquisar,#btnPesquisar,#sbmProtocoloPesquisa')||[...document.querySelectorAll('button,input[type=submit],input[type=button]')].find(e=>/pesquisar/i.test(e.value||e.innerText||''));if(b)b.click();const f=document.querySelector('form[action*=pesquisa],#frmPesquisa');if(f&&!b)f.submit();}""")
                try:
                    await pg.keyboard.press("Enter")
                except Exception:
                    pass
                try:
                    await pg.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                await pg.wait_for_timeout(4000)
                # DEBUG: estado pós-submit (a busca disparou? campo hidden do contato setado?)
                dbg = await pg.evaluate(r"""()=>{
                  const hid=[...document.querySelectorAll('input[type=hidden]')].filter(e=>/contato|interess|protocolo/i.test(e.name||e.id||'')&&e.value).map(e=>(e.name||e.id)+'='+e.value).slice(0,4);
                  const reg=(document.body.innerText.match(/(\d+)\s+registr|nenhum registro|Lista de Processos|filtrado por/i)||[])[0]||'';
                  return {url:location.href.slice(-60), hiddenContato:hid, regMsg:reg};}""")
                print("DEBUG pós-submit:", dbg, flush=True)
                txt = await pg.inner_text("body")
                procs = sorted(set(re.findall(r"SEI[- ]?\d{6}/\d{6}/\d{4}", txt)))
                # também captura os links de resultado com o objeto
                itens = await pg.evaluate(r"""()=>[...document.querySelectorAll('a')].map(a=>(a.innerText||'').trim()).filter(x=>/\d{6}\/\d{6}\/\d{4}|contrat|005\/2021|MGS/i.test(x)).slice(0,40)""")
                print(f"\nPROCESSOS encontrados ({len(procs)}):")
                for p in procs[:50]:
                    print("  ", p)
                print("itens relevantes:", itens[:20])
        finally:
            await b.close()


asyncio.run(main())
