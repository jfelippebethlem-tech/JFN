#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extração de fonte primária v2: abre o processo EM-SESSÃO (sei_reader.ler_processo) e então, para cada
doc, lê o frame de conteúdo; se for scan (PDF/imagem), BAIXA os bytes e roda OCR (corrige o gargalo do
gatilho ≤50 chars). Foco: NF/OB/NL do processo 2026 (tem o relatório + os anexos)."""
import asyncio, json, re, sys
from pathlib import Path
sys.path.insert(0, "/home/ubuntu/JFN")
from tools import sei_reader as SR
from compliance_agent.sei.ocr_docs import ocr_documento

PROC = "SEI-330005/000030/2026"
ALVO = re.compile(r"^(anexo$|anexo ob|despacho de formaliza|nota|comprovante|extrato)", re.I)


async def conteudo_forte(pg, doc):
    """Lê o doc em-sessão: tenta innerText de TODOS os frames; se nada substantivo, baixa bytes + OCR."""
    try:
        await pg.goto(doc["url"], wait_until="domcontentloaded", timeout=25000)
        await pg.wait_for_timeout(1200)
    except Exception as e:
        return {"via": "erro", "conteudo": f"goto: {e}"}
    # 1) texto nativo do melhor frame (ignora menu/casca)
    melhor = ""
    srcs = []
    for fr in pg.frames:
        try:
            t = await fr.evaluate("()=>document.body?document.body.innerText:''")
        except Exception:
            t = ""
        if t and "Autenticação em dois fatores" not in t and len(t) > len(melhor):
            melhor = t
        # coleta srcs de iframe/embed/object (o PDF real)
        try:
            s = await fr.evaluate("""()=>[...document.querySelectorAll('iframe,embed,object')].map(e=>e.src||e.data).filter(Boolean)""")
            srcs += s or []
        except Exception:
            pass
    if melhor and len(melhor) > 120 and not melhor.strip().startswith("GOVERNO DO ESTADO"):
        return {"via": "html-frame", "conteudo": melhor}
    # 2) scan → baixa bytes (sessão) + OCR. Tenta o src do embed; senão o próprio url.
    for u in (srcs + [doc["url"]]):
        try:
            resp = await pg.context.request.get(u)
            if not resp.ok:
                continue
            ct = (resp.headers.get("content-type") or "").lower()
            if "pdf" in ct or u.lower().endswith(".pdf"):
                tipo = "pdf"
            elif ct.startswith("image/"):
                tipo = "imagem"
            elif "html" in ct:
                continue
            else:
                continue
            body = await resp.body()
            loop = asyncio.get_event_loop()
            txt = await loop.run_in_executor(None, lambda: ocr_documento(body, tipo=tipo))
            if txt and len(txt) > 40:
                return {"via": "ocr", "conteudo": txt, "src": u[:80]}
        except Exception:
            continue
    return {"via": "vazio", "conteudo": melhor[:200]}


async def main():
    from compliance_agent.recursos import browser_lock_async, aguardar_load_async
    from playwright.async_api import async_playwright
    await aguardar_load_async(max_por_core=1.5, espera_max=90)
    out = []
    async with browser_lock_async(espera_max=600), async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"])
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page()
        try:
            if not await SR.login(pg, tentativas=30):
                print("LOGIN FALHOU"); return
            print("login itkava OK; abrindo processo em-sessão…", flush=True)
            res = await SR.ler_processo(pg, PROC, usar_cache=False)   # abre o processo (sessão válida)
            docs = [d for d in (res.get("documentos") or []) if d.get("url") and ALVO.search((d.get("titulo") or ""))]
            print(f"{len(docs)} docs-alvo no {PROC}", flush=True)
            for doc in docs[:7]:
                r = await conteudo_forte(pg, doc)
                cont = r.get("conteudo", "")
                nf = sorted(set(re.findall(r"(?:nota fiscal|NFS?-?e?\.?)\s*[:nº]*\s*(\d{2,9})", cont, re.I)))[:8]
                val = sorted(set(re.findall(r"[\d.]{3,12},\d{2}", cont)))[:10]
                comp = sorted(set(re.findall(r"(?:compet[êe]ncia|refer[êe]nte|per[íi]odo)[^\n]{0,35}", cont, re.I)))[:5]
                print(f"  • {doc['titulo'][:38]:<38} via={r['via']:<10} {len(cont)}c | NF={nf} R$={val[:4]} comp={comp[:1]}", flush=True)
                out.append({"titulo": doc["titulo"], "via": r["via"], "nf": nf, "valores": val, "competencia": comp, "texto": cont[:2000]})
        finally:
            await b.close()
    Path("data/sei_cache/primarios_v2.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("SALVO data/sei_cache/primarios_v2.json")


asyncio.run(main())
