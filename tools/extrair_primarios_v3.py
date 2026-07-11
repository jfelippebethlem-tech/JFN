#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extração SEI v3 (wiring corrigido): abre processo em-sessão, e por doc usa request.get (sessão
autenticada) p/ pegar os BYTES — se HTML, segue o iframe/embed do arquivo real; se PDF/imagem, OCR.
Resolve o ERR_ABORTED do goto direto em scan. Engine OCR: tesseract/poppler/fitz (instalados)."""
import asyncio
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, "/home/ubuntu/JFN")
from tools import sei_reader as SR
from compliance_agent.sei.ocr_docs import ocr_documento

PROC = sys.argv[1] if len(sys.argv) > 1 else "SEI-330005/000030/2026"
BASE = "https://sei.rj.gov.br/sei/"


def _ocr(body, tipo):
    try:
        return ocr_documento(body, tipo=tipo) or ""
    except Exception as e:
        return f"[ocr-erro: {e}]"


async def conteudo_forte(pg, doc):
    url = doc["url"]
    try:
        resp = await pg.context.request.get(url, timeout=40000)
        ct = (resp.headers.get("content-type") or "").lower()
        body = await resp.body()
    except Exception as e:
        return {"via": "erro", "conteudo": f"req: {str(e)[:100]}"}
    if "pdf" in ct or url.lower().endswith(".pdf"):
        return {"via": "ocr-pdf", "conteudo": _ocr(body, "pdf")}
    if ct.startswith("image/"):
        return {"via": "ocr-img", "conteudo": _ocr(body, "imagem")}
    # HTML: pode ser doc-editor (texto inline) OU casca com iframe/embed do arquivo real
    html = body.decode("utf-8", "ignore")
    if "Autenticação em dois fatores" in html or "login.php" in html:
        return {"via": "sem-sessao", "conteudo": ""}
    srcs = re.findall(r'(?:src|data)=["\']([^"\']+)["\']', html)
    for s in srcs:
        if "documento" not in s and "arquivo" not in s and "download" not in s:
            continue
        su = s if s.startswith("http") else BASE + s.lstrip("./")
        su = su.replace("&amp;", "&")
        try:
            r2 = await pg.context.request.get(su, timeout=40000)
            ct2 = (r2.headers.get("content-type") or "").lower()
            b2 = await r2.body()
            if "pdf" in ct2:
                return {"via": "ocr-iframe-pdf", "conteudo": _ocr(b2, "pdf"), "src": su[:70]}
            if ct2.startswith("image/"):
                return {"via": "ocr-iframe-img", "conteudo": _ocr(b2, "imagem"), "src": su[:70]}
            if "html" in ct2 and len(b2) > 1500:
                t = re.sub(r"<[^>]+>", " ", b2.decode("utf-8", "ignore"))
                t = re.sub(r"\s+", " ", t)
                if len(t) > 200:
                    return {"via": "html-iframe", "conteudo": t, "src": su[:70]}
        except Exception:
            continue
    # fallback: texto do próprio HTML (doc-editor)
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    return {"via": "html", "conteudo": t}


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
            print(f"login itkava OK; abrindo {PROC} em-sessão…", flush=True)
            res = await SR.ler_processo(pg, PROC, usar_cache=False)
            docs = res.get("documentos") or []
            via = "normal"
            if not docs:  # FIX: 330005 precisa do método CRACKED (como SR.ler() faz) — meu erro era pular isso
                print("  normal=0 → fallback CRACKED…", flush=True)
                try:
                    dump = await SR._ler_cracked(pg, PROC)
                    if dump.get("documentos"):
                        res = await SR._montar_resultado_cracked(pg, PROC, dump, False)
                        docs = res.get("documentos") or []
                        via = "cracked"
                except Exception as e:
                    print("  cracked erro:", str(e)[:100], flush=True)
            print(f"{len(docs)} docs no processo (via {via})", flush=True)
            for doc in docs:
                r = await conteudo_forte(pg, doc)
                cont = r.get("conteudo", "") or ""
                nf = sorted(set(re.findall(r"(?:nota fiscal|NFS?-?e?\.?)[^\d]{0,12}(\d{3,9})", cont, re.I)))[:6]
                val = sorted(set(re.findall(r"R?\$?\s?\d{1,3}(?:\.\d{3})*,\d{2}", cont)))[:10]
                comp = sorted(set(re.findall(r"(?:compet[êe]ncia|refer[êe]nte|m[êe]s)[^\n]{0,30}", cont, re.I)))[:4]
                print(f"  • {(doc.get('titulo') or '?')[:34]:<34} via={r['via']:<14} {len(cont)}c NF={nf} R$={val[:3]}", flush=True)
                out.append({"titulo": doc.get("titulo"), "via": r["via"], "nf": nf, "valores": val,
                            "competencia": comp, "texto": cont[:3000]})
        finally:
            await b.close()
    Path(f"data/sei_cache/primarios_v3_{re.sub(r'[^0-9]','',PROC)}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("SALVO.")


asyncio.run(main())
