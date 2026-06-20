#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lê a ÁRVORE COMPLETA de um processo SEI (não só os ~10 docs do preview da pesquisa) e dá OCR
SÓ nos docs-alvo (planilha/proposta/edital/contrato/NF). Conserta o cap de 10: após a pesquisa
cracked, CLICA o processo p/ abrir o procedimento_trabalhar e lê a ifrArvore inteira.

GUARDADO p/ não travar a VM (2 vCPU, já travou 3x): vm_guard.preflight + cleanup_orphans; OCR
limitado; FOREGROUND serial. Uso:
    SEI_MAX_DOCS=120 .venv/bin/python tools/sei_arvore_completa.py "330020/000762/2021" "planilha|proposta|edital|composi|custo|encargo|nota fiscal|NF|contrato|termo de refer"
"""
import os, sys, re, json, asyncio
from pathlib import Path
sys.path.insert(0, "/home/ubuntu/JFN")
from tools import sei_reader as SR
from tools import vm_guard as G
from playwright.async_api import async_playwright

PROC = sys.argv[1] if len(sys.argv) > 1 else "330020/000762/2021"
KW = sys.argv[2] if len(sys.argv) > 2 else r"planilha|proposta|edital|composi|custo|encargo|nota fiscal|\bNF\b|contrato|termo de refer|or[çc]ament|ata"
MAX_OCR = int(os.environ.get("SEI_OCR_DOCS", "6"))
TAG = re.sub(r"[^0-9]", "_", PROC)


async def todos_docs_dos_frames(pg):
    docs = {}
    for fr in pg.frames:
        try:
            ds = await fr.evaluate(r"""()=>[...document.querySelectorAll('a[href*="documento_visualizar"],a[href*="acessar_documento"]')].map(a=>{const p=a.closest('tr,li,div,span');return {t:(a.title||a.textContent||'').trim().slice(0,70),pai:(p?p.textContent:'').replace(/\s+/g,' ').trim().slice(0,90),u:a.href};})""")
            for d in ds:
                docs[d["u"]] = d
        except Exception:
            pass
    return list(docs.values())


async def main():
    G.cleanup_orphans()
    ok, motivo = G.preflight()
    print("PREFLIGHT:", ok, motivo, flush=True)
    if not ok:
        ok, motivo = G.wait_until_safe(150)
        print("após espera:", ok, motivo, flush=True)
        if not ok:
            return
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
            # pesquisa cracked (deixa nos resultados)
            try:
                await SR._ler_cracked(pg, PROC)
            except Exception as e:
                print("cracked:", str(e)[:60], flush=True)
            await pg.wait_for_timeout(2000)
            antes = await todos_docs_dos_frames(pg)
            print(f"docs no PREVIEW da pesquisa: {len(antes)}", flush=True)
            # ABRIR o processo: clicar o link procedimento_trabalhar/visualizar do número
            alvo_num = re.sub(r"\D", "", PROC)[:6]
            abriu = None
            for fr in pg.frames:
                try:
                    href = await fr.evaluate(r"""(num)=>{const as=[...document.querySelectorAll('a[href]')];
                        const a=as.find(x=>/procedimento_trabalhar|procedimento_visualizar|procedimento_controlar/i.test(x.href||'')&&(x.href||'').includes('id_procedimento'));
                        return a?a.href:null;}""", alvo_num)
                    if href:
                        abriu = href; break
                except Exception:
                    pass
            if abriu:
                try:
                    async with pg.expect_navigation(wait_until="domcontentloaded", timeout=25000):
                        await pg.goto(abriu, wait_until="domcontentloaded", timeout=25000)
                except Exception:
                    pass
                # espera ATIVA a ifrArvore montar a árvore inteira
                for _ in range(10):
                    await pg.wait_for_timeout(1500)
                    if any("arvore" in (f.url or "").lower() for f in pg.frames):
                        await pg.wait_for_timeout(1500); break
            docs = await todos_docs_dos_frames(pg)
            print(f"\n=== ÁRVORE COMPLETA: {len(docs)} documentos ===", flush=True)
            for i, d in enumerate(docs):
                print(f"  [{i:3}] {(d['t'] or d['pai'][:55])}", flush=True)
            Path(f"data/sei_cache/arvore_{TAG}.json").write_text(json.dumps(docs, ensure_ascii=False))
            # alvos p/ OCR
            alvo = [d for d in docs if re.search(KW, (d["t"] + " " + d["pai"]), re.I)]
            print(f"\n⭐ {len(alvo)} docs-alvo (kw='{KW}'):", [ (d['t'] or d['pai'][:40])[:45] for d in alvo[:30]], flush=True)
            # OCR só dos alvos (limite + páginas capadas no ocr_documento)
            from compliance_agent.sei.ocr_docs import ocr_documento
            feitos = 0
            for d in alvo:
                if feitos >= MAX_OCR:
                    print(f"  [stop OCR: limite {MAX_OCR}]", flush=True); break
                G.cleanup_orphans()
                try:
                    resp = await ctx.request.get(d["u"], timeout=45000)
                    body = await resp.body()
                    ct = (resp.headers.get("content-type") or "").lower()
                    tipo = "pdf" if "pdf" in ct else ("image" if "image" in ct else "pdf")
                    txt = await asyncio.get_event_loop().run_in_executor(None, lambda: ocr_documento(body, tipo=tipo) or "")
                    nome = re.sub(r"[^0-9A-Za-z]", "_", (d["t"] or "doc")[:32])
                    Path(f"data/sei_cache/ocr_{TAG}_{feitos:02d}_{nome}.txt").write_text(txt)
                    sig = len(re.findall(r"remunera|encargo|m[óo]dulo|insumo|BDI|sal[áa]rio|R\$ ?[0-9]", txt, re.I))
                    print(f"  OCR[{feitos}] '{(d['t'] or '')[:38]}' → {len(txt)}c  sinais={sig}", flush=True)
                    feitos += 1
                except Exception as e:
                    print(f"  OCR erro: {str(e)[:60]}", flush=True)
        finally:
            await b.close()
    G.cleanup_orphans()


asyncio.run(main())
