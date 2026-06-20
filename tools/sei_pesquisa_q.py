#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SEI Pesquisa avançada (campo `q` = Texto para Pesquisa, busca CONTEÚDO dos documentos).
Roda vários termos numa só sessão e lista os processos achados — p/ achar o processo da
contratação do contrato 005/2021 (MGS Clean) que guarda a planilha de custos."""
import asyncio, sys, re, json
sys.path.insert(0, "/home/ubuntu/JFN")
from tools import sei_reader as SR

TERMOS = sys.argv[1:] or ["005/2021 MGS", "MGS Clean Soluções", "planilha de custos MGS", "19.088.605/0001-04"]


async def selecionar_orgao_iterj(pg):
    """Abre o multiselect 'Órgão Gerador' e marca ITERJ (idms-drop) — restringe a busca ao ITERJ."""
    try:
        await pg.evaluate(r"""()=>{const c=document.getElementById('selOrgaoPesquisa')||document.querySelector('[name="selOrgaoPesquisa[]"]');
            if(c){const d=c.closest('.idms-container,.multiselect,div');(d||c).click();}
            const t=[...document.querySelectorAll('.idms-search,.idms-container input[type=text],input[placeholder*=rg]')][0];if(t)t.click();}""")
        await pg.wait_for_timeout(800)
        ok = await pg.evaluate(r"""()=>{const labs=[...document.querySelectorAll('label,span,li,div')];
            const it=labs.find(e=>/^ITERJ$/.test((e.innerText||'').trim()));
            if(it){const cb=it.querySelector('input[type=checkbox]')||it.previousElementSibling||document.getElementById('idms-drop input[type=\'checkbox\']42');
                (cb&&cb.click)?cb.click():it.click();return true;}return false;}""")
        await pg.wait_for_timeout(600)
        print("órgão ITERJ marcado:", ok, flush=True)
    except Exception as e:
        print("selOrgao erro:", str(e)[:70], flush=True)


async def buscar(pg, termo):
    # garante que estamos na página de Pesquisa (campo q presente)
    if not await pg.query_selector('[name="q"]'):
        await pg.evaluate(r"""()=>{const e=[...document.querySelectorAll('a')].find(a=>/^pesquisa$/i.test((a.innerText||'').trim()));if(e)e.click();}""")
        await pg.wait_for_timeout(4000)
    await selecionar_orgao_iterj(pg)
    await pg.evaluate(r"""(t)=>{
        const q=document.querySelector('[name="q"]')||document.getElementById('q');
        if(q){q.value=t;q.focus();q.dispatchEvent(new Event('input',{bubbles:true}));}
        // radio: pesquisar em Processos; considerar documentos
        const rp=document.getElementById('optProcessos'); if(rp)rp.checked=true;
        const cd=document.getElementById('chkSinConsiderarDocumentos'); if(cd&&!cd.checked)cd.click();
    }""", termo)
    await pg.wait_for_timeout(800)
    # submit: botão Pesquisar (id/valor) ou Enter
    await pg.evaluate(r"""()=>{const b=document.querySelector('#sbmPesquisar,#btnPesquisar')||[...document.querySelectorAll('button,input[type=submit],input[type=button],a')].find(e=>/^pesquisar$/i.test((e.value||e.innerText||'').trim()));if(b)b.click();}""")
    try:
        await pg.keyboard.press("Enter")
    except Exception:
        pass
    try:
        await pg.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    await pg.wait_for_timeout(3500)
    txt = await pg.inner_text("body")
    procs = sorted(set(re.findall(r"\b\d{6}/\d{6}/\d{4}\b", txt)))
    # linhas de resultado: link + objeto/descrição
    itens = await pg.evaluate(r"""()=>{
        const out=[];
        document.querySelectorAll('a').forEach(a=>{const t=(a.innerText||'').trim();
            if(/\d{6}\/\d{6}\/\d{4}/.test(t)||/contrat|planilha|preg[ãa]o|termo de ref|005\/2021/i.test(t)) out.push(t.slice(0,90));});
        return out.slice(0,40);}""")
    nres = re.search(r"(\d+)\s+registro", txt, re.I)
    return {"termo": termo, "n": nres.group(1) if nres else "?", "procs": procs[:40], "itens": itens[:25]}


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
            print("login OK; pesquisando…", flush=True)
            res = []
            for t in TERMOS:
                try:
                    r = await buscar(pg, t)
                    res.append(r)
                    print(f"\n=== '{t}' → {r['n']} registros; {len(r['procs'])} processos ===", flush=True)
                    for p in r["procs"]: print("   proc:", p, flush=True)
                    for it in r["itens"][:12]: print("   item:", it, flush=True)
                except Exception as e:
                    print(f"erro '{t}':", str(e)[:90], flush=True)
            from pathlib import Path
            Path("data/sei_cache/sei_pesquisa_q.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
            print("\nSALVO data/sei_cache/sei_pesquisa_q.json", flush=True)
        finally:
            await b.close()


asyncio.run(main())
