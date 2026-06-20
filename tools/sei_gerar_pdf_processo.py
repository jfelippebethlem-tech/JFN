#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera a ÍNTEGRA (PDF do Processo) de um processo SEI via a função nativa "Gerar Arquivo PDF do
Processo" e salva. Guardado (vm_guard). Uso:
  .venv/bin/python tools/sei_gerar_pdf_processo.py "330020/000762/2021"
"""
import os, sys, re, asyncio
from pathlib import Path
sys.path.insert(0, "/home/ubuntu/JFN")
from tools import sei_reader as SR
from tools import vm_guard as G
from playwright.async_api import async_playwright

PROC = sys.argv[1]
TAG = re.sub(r"[^0-9]", "_", PROC)
OUT = Path(f"data/sei_cache/integra_{TAG}.pdf")


async def main():
    G.cleanup_orphans()
    ok, m = G.preflight()
    print("PREFLIGHT:", ok, m, flush=True)
    if not ok:
        ok, m = G.wait_until_safe(150)
        if not ok: return
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=G.guarded_launch_args())
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR", accept_downloads=True,
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page(); await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            if not await SR.login(pg, tentativas=25): print("LOGIN FALHOU"); return
            print("login OK", flush=True)
            try: await SR._ler_cracked(pg, PROC)
            except Exception as e: print("crk", str(e)[:40], flush=True)
            await pg.wait_for_timeout(2500)
            # id_procedimento da URL de qualquer frame
            idp = None
            for fr in pg.frames:
                mm = re.search(r"id_procedimento=(\d+)", fr.url or "")
                if mm: idp = mm.group(1); break
            print("id_procedimento:", idp, flush=True)
            # procura o ícone/link "Gerar Arquivo PDF do Processo" em qualquer frame
            alvo = None
            for fr in pg.frames:
                try:
                    h = await fr.evaluate(r"""()=>{const e=[...document.querySelectorAll('a,img,button')].find(x=>/gerar.*pdf|pdf do processo|procedimento_gerar_pdf/i.test((x.title||x.alt||x.href||x.getAttribute&&x.getAttribute('onclick')||'')));return e?(e.href|| (e.closest&&e.closest('a')&&e.closest('a').href)||''):null;}""")
                    if h: alvo = h; print("link gerar-pdf:", h[:90], flush=True); break
                except Exception: pass
            target = alvo
            if not target and idp:
                # constrói a URL da ação (reusa infra params de um link existente)
                base = None
                for fr in pg.frames:
                    mm = re.search(r"(https://sei\.rj\.gov\.br/sei/controlador\.php\?[^\"']*infra_hash=[0-9a-f]+)", await fr.content())
                    if mm: base = mm.group(1); break
                if base:
                    inf = dict(re.findall(r"(infra_sistema|infra_unidade_atual|infra_hash)=([^&\"']+)", base))
                    target = f"https://sei.rj.gov.br/sei/controlador.php?acao=procedimento_gerar_pdf&id_procedimento={idp}&infra_sistema={inf.get('infra_sistema','')}&infra_unidade_atual={inf.get('infra_unidade_atual','')}&infra_hash={inf.get('infra_hash','')}"
            if not target:
                print("NÃO achei a ação Gerar PDF"); return
            await pg.goto(target, wait_until="domcontentloaded", timeout=40000)
            await pg.wait_for_timeout(2500)
            # seleciona 'todos os documentos disponíveis' + clica Gerar; captura download
            await pg.evaluate(r"""()=>{document.querySelectorAll('input[type=radio]').forEach(r=>{if(/todos|dispon/i.test((r.parentElement?r.parentElement.innerText:'')+(r.value||'')))try{r.checked=true;r.click()}catch(e){}});}""")
            try:
                async with pg.expect_download(timeout=120000) as di:
                    await pg.evaluate(r"""()=>{const b=[...document.querySelectorAll('button,input[type=button],input[type=submit],a')].find(e=>/gerar/i.test(e.value||e.innerText||''));if(b)b.click();}""")
                dl = await di.value
                await dl.save_as(str(OUT))
                print(f"ÍNTEGRA salva: {OUT} ({OUT.stat().st_size//1024}KB)", flush=True)
            except Exception as e:
                print("download não veio:", str(e)[:80], flush=True)
        finally:
            await b.close()
    G.cleanup_orphans()


asyncio.run(main())
