#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lê TODOS os documentos de um processo SEI percorrendo a PAGINAÇÃO da Pesquisa cracked
(20 docs/página + 'Próxima'). Conserta o cap real: o preview mostrava só a 1a página.
Depois dá OCR SÓ nos docs-alvo (planilha/proposta/edital/NF/medição). GUARDADO (vm_guard).

Uso: SEI_OCR_DOCS=4 .venv/bin/python tools/sei_proc_paginado.py "330020/000762/2021" "planilha|proposta|composi|custo|encargo|edital|nota fiscal|medi..o"
"""
import os
import sys
import re
import json
import asyncio
from pathlib import Path
sys.path.insert(0, "/home/ubuntu/JFN")
from tools import sei_reader as SR
from tools import vm_guard as G
from playwright.async_api import async_playwright

PROC = sys.argv[1] if len(sys.argv) > 1 else "330020/000762/2021"
KW = sys.argv[2] if len(sys.argv) > 2 else r"planilha|proposta|composi|custo|encargo|edital|nota fiscal|medi[çc][ãa]o|termo de refer|or[çc]ament"
MAX_OCR = int(os.environ.get("SEI_OCR_DOCS", "4"))
MAX_PAG = int(os.environ.get("SEI_MAX_PAG", "25"))
TAG = re.sub(r"[^0-9]", "_", PROC)


async def docs_da_pagina(pg):
    docs = {}
    for fr in pg.frames:
        try:
            ds = await fr.evaluate(r"""()=>[...document.querySelectorAll('a[href*="documento_visualizar"],a[href*="acessar_documento"]')].map(a=>{const p=a.closest('tr,li,div');return {t:(a.title||a.textContent||'').trim().slice(0,75),pai:(p?p.textContent:'').replace(/\s+/g,' ').trim().slice(0,90),u:a.href};})""")
            for d in ds:
                docs[d["u"]] = d
        except Exception:
            pass
    return docs


async def clicar_proxima(pg, offset):
    """Pagina via navegar('<offset>') do SEI, com RETRY (o frame de resultados re-renderiza e perde
    a função navegar momentaneamente — flakiness que travava a paginação na pág. 5)."""
    for tentativa in range(4):
        for fr in pg.frames:
            try:
                if await fr.evaluate("()=>typeof navegar==='function'"):
                    await fr.evaluate("(o)=>{ try{ navegar(o); }catch(e){} }", str(offset))
                    return True
            except Exception:
                pass
        await pg.wait_for_timeout(1500)  # espera o frame re-renderizar e tenta de novo
    return False


async def main():
    G.cleanup_orphans()
    ok, motivo = G.preflight()
    print("PREFLIGHT:", ok, motivo, flush=True)
    if not ok:
        ok, motivo = G.wait_until_safe(150)
        if not ok:
            print("VM ocupada:", motivo); return
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=G.guarded_launch_args())
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page()
        await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            if not await SR.login(pg, tentativas=25):
                print("LOGIN FALHOU"); return
            print("login OK", flush=True)
            try:
                await SR._ler_cracked(pg, PROC)
            except Exception as e:
                print("cracked:", str(e)[:50], flush=True)
            await pg.wait_for_timeout(2000)
            todos = {}
            zero = 0
            for pagina in range(1, MAX_PAG + 1):
                d = await docs_da_pagina(pg)
                novos = {u: v for u, v in d.items() if u not in todos}
                todos.update(d)
                print(f"  página {pagina}: +{len(novos)} docs (total {len(todos)})", flush=True)
                zero = zero + 1 if not novos else 0
                if zero >= 3:
                    print("  [fim: 3 páginas sem docs novos]", flush=True); break
                if not await clicar_proxima(pg, pagina * 10):
                    print(f"  [fim: frame de resultados sem navegar() na página {pagina}]", flush=True); break
                await pg.wait_for_timeout(3600)
            docs = list(todos.values())
            print(f"\n=== TOTAL {len(docs)} documentos no processo {PROC} ===", flush=True)
            for i, x in enumerate(docs):
                print(f"  [{i:3}] {(x['t'] or x['pai'][:55])}", flush=True)
            Path(f"data/sei_cache/paginado_{TAG}.json").write_text(json.dumps(docs, ensure_ascii=False))
            alvo = [x for x in docs if re.search(KW, (x["t"] + " " + x["pai"]), re.I)]
            print(f"\n⭐ {len(alvo)} docs-alvo:", [(x['t'] or x['pai'][:35])[:45] for x in alvo[:30]], flush=True)
            from compliance_agent.sei.ocr_docs import ocr_documento
            feitos = 0
            for x in alvo:
                if feitos >= MAX_OCR:
                    print(f"  [stop OCR: limite {MAX_OCR}; restam {len(alvo)-feitos} alvos]", flush=True); break
                try:  # NÃO chamar cleanup_orphans aqui: mataria o próprio browser em uso!
                    resp = await ctx.request.get(x["u"], timeout=45000)
                    body = await resp.body()
                    ct = (resp.headers.get("content-type") or "").lower()
                    tipo = "pdf" if "pdf" in ct else ("image" if "image" in ct else "pdf")
                    txt = await asyncio.get_event_loop().run_in_executor(None, lambda: ocr_documento(body, tipo=tipo) or "")
                    nome = re.sub(r"[^0-9A-Za-z]", "_", (x["t"] or "doc")[:30])
                    Path(f"data/sei_cache/ocr_{TAG}_{feitos:02d}_{nome}.txt").write_text(txt)
                    sig = len(re.findall(r"remunera|encargo|m[óo]dulo|insumo|BDI|sal[áa]rio|R\$ ?[0-9]|piso", txt, re.I))
                    print(f"  OCR[{feitos}] '{(x['t'] or '')[:40]}' → {len(txt)}c sinais={sig}", flush=True)
                    feitos += 1
                except Exception as e:
                    print(f"  OCR erro: {str(e)[:55]}", flush=True)
        finally:
            await b.close()
    G.cleanup_orphans()


if __name__ == "__main__":
    asyncio.run(main())
