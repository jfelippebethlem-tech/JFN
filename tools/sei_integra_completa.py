#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÍNTEGRA COMPLETA de um processo SEI: pagina TODOS os documentos, baixa cada um (PDF ou HTML→PDF),
junta num PDF único e ENVIA ao Telegram (divide em partes <45MB). OCR opcional via SEI_INTEGRA_OCR=1 (default OFF — escaneado entra com as páginas originais + texto OCR; sem a flag, comportamento antigo). Guardado.
Uso: .venv/bin/python tools/sei_integra_completa.py "330020/000762/2021"
"""
import os
import sys
import re
import asyncio
from pathlib import Path
sys.path.insert(0, "/home/ubuntu/JFN")
from tools import sei_reader as SR
from tools import vm_guard as G
from playwright.async_api import async_playwright, Error as PWError
import httpx
import fitz

PROC = sys.argv[1]
TAG = re.sub(r"[^0-9]", "_", PROC)
MAX_PAG = int(os.environ.get("SEI_MAX_PAG", "40"))
OCR_ON = os.environ.get("SEI_INTEGRA_OCR", "0") == "1"   # OFF por padrão (peso na VM 2 vCPU)
ENV = Path("/home/ubuntu/.hermes/.env")
def _k(n):
    m = re.search(rf"^{n}=(.+)$", ENV.read_text(), re.M); return m.group(1).strip().strip('"').strip("'") if m else ""
TOK, CHAT = _k("TELEGRAM_BOT_TOKEN"), _k("TELEGRAM_CHAT_ID")


def envia(path, caption):
    with open(path, "rb") as f:
        return httpx.post(f"https://api.telegram.org/bot{TOK}/sendDocument",
                          data={"chat_id": CHAT, "caption": caption[:1000]},
                          files={"document": (Path(path).name, f, "application/pdf")}, timeout=300).json().get("ok")


async def main():
    G.cleanup_orphans()
    ok, m = G.preflight()
    print("PREFLIGHT:", ok, m, flush=True)
    if not ok:
        ok, m = G.wait_until_safe(150)
        if not ok: return
    outdir = Path(f"data/sei_cache/integra_{TAG}"); outdir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=G.guarded_launch_args())
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page(); await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            if not await SR.login(pg, tentativas=25): print("LOGIN FALHOU"); return
            print("login OK", flush=True)
            # ENUMERAÇÃO — caminho CRACKED primeiro (mesmo do ler() canônico): abre processos de OUTRA
            # unidade que o itkava VÊ mas o abrir_processo/arvore_do_fonte não abre (070002/INEA,
            # 070026/SEAS). Provado 2026-07-13: INEA 070002/004135/2025 = 274 docs via cracked. Fallback:
            # arvore_do_fonte (unidade do login). Os docs trazem {titulo,url}; a url é o nó arvore_visualizar.
            arv = []
            try:
                dump = await SR._ler_cracked(pg, PROC)
                arv = dump.get("documentos") or []
            except (PWError, asyncio.TimeoutError) as e:
                print(f"cracked: {str(e)[:60]}", flush=True)
            if not arv:
                fr = await SR.abrir_processo(pg, PROC)
                if fr:
                    arv = await SR.arvore_do_fonte(pg)
            if not arv:
                print("SEM ÁRVORE (processo não abriu)"); return
            # formato p/ o resto do script: {t: titulo, u: url, pai: ''}
            docs = [{"t": d.get("titulo") or d.get("texto") or "", "u": d.get("url") or "", "pai": ""}
                    for d in arv if d.get("url")]
            print(f"baixando {len(docs)} docs…", flush=True)
            paths = []

            async def baixa_um(x, fp):
                # CONTEÚDO via _conteudo_doc (drill no iframe, MESMA sessão) — é o que FUNCIONA cross-unit
                # (o GET direto do ctx.request voltava um PDF em branco de ~1KB, passando falso-positivo).
                # O GET só é tentado quando confiável: PDF com >2KB E texto extraível (docs da unidade do login).
                try:
                    resp = await ctx.request.get(SR._url_conteudo_doc(x["u"]), timeout=12000)
                    body = await resp.body()
                    if body[:5] == b"%PDF-" and len(body) > 2048:
                        import fitz as _f
                        _d = _f.open(stream=body, filetype="pdf")
                        if _d.page_count and sum(len(p.get_text()) for p in _d) > 40:
                            fp.write_bytes(body); _d.close(); return True
                        # SEI_INTEGRA_OCR=1: PDF escaneado (tem IMAGEM, não tem texto) entra na
                        # íntegra com as páginas originais + página de texto OCR quando possível
                        # (antes: doc simplesmente FALTAVA na íntegra — medição/NF escaneada sumia).
                        # O guard de imagem separa o escaneado real do "PDF em branco" cross-unit.
                        if OCR_ON and _d.page_count and any(p.get_images() for p in _d):
                            fp.write_bytes(body)
                            try:
                                from compliance_agent.sei.ocr_docs import ocr_documento
                                txt_ocr = (ocr_documento(body) or "").strip()
                                if len(txt_ocr) > 60:
                                    _o = _f.open(str(fp))
                                    pg_o = _o.new_page()
                                    pg_o.insert_textbox(_f.Rect(40, 40, 555, 800),
                                                        f"[OCR — {x['t']}]\n\n" + txt_ocr[:6000],
                                                        fontsize=8)
                                    _o.saveIncr(); _o.close()
                            except (ImportError, RuntimeError, OSError, ValueError) as e_ocr:
                                # OCR indisponível → fica só o escaneado original (já é ganho)
                                print(f"  ocr pulado ({x['t'][:30]}): {str(e_ocr)[:40]}", flush=True)
                            _d.close(); return True
                        _d.close()
                except (PWError, RuntimeError, ValueError, OSError):
                    pass
                c = await SR._conteudo_doc(pg, {"url": x["u"], "texto": x["t"]})
                txt = ((c or {}).get("conteudo") or "").strip()
                if len(txt) < 15:
                    return False
                doc = fitz.open()
                doc.new_page().insert_textbox(fitz.Rect(40, 40, 555, 800), f"[{x['t']}]\n\n" + txt[:6000], fontsize=8)
                rest = txt[6000:]
                while rest:
                    doc.new_page().insert_textbox(fitz.Rect(40, 40, 555, 800), rest[:6500], fontsize=8); rest = rest[6500:]
                doc.save(str(fp)); doc.close(); return True

            manifest = []
            for i, x in enumerate(docs):
                fp = outdir / f"{i:03d}.pdf"
                ok = False
                try:
                    if await asyncio.wait_for(baixa_um(x, fp), timeout=int(os.environ.get("SEI_DOC_TIMEOUT", "15"))):
                        paths.append(fp); ok = True
                except (asyncio.TimeoutError, PWError, httpx.HTTPError, RuntimeError, OSError, ValueError) as e:
                    print(f"  doc {i} pulado: {str(e)[:35]}", flush=True)
                manifest.append({"i": i, "arquivo": fp.name, "titulo": x.get("t") or "",
                                 "contexto": x.get("pai") or "", "url": x.get("u") or "",
                                 "ok": ok})
                if i % 15 == 0:
                    print(f"  {i}/{len(docs)} ({len(paths)} ok)", flush=True)
            # manifest com os TÍTULOS da árvore: é ele que permite classificar a
            # fase de cada documento depois (tools/sei_arquivar.py)
            import json as _json
            (outdir / "manifest.json").write_text(
                _json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
            # junta
            out = fitz.open()
            sep = fitz.open(); spg = sep.new_page(); spg.insert_text((60, 120), f"ÍNTEGRA — PROCESSO SEI-{PROC} ({len(paths)} documentos)", fontsize=14); out.insert_pdf(sep); sep.close()
            for fp in paths:
                try:
                    s = fitz.open(str(fp))
                    if s.is_pdf and s.page_count: out.insert_pdf(s)
                    s.close()
                except (RuntimeError, ValueError, OSError): pass
            full = Path(f"data/sei_cache/INTEGRA_{TAG}.pdf"); out.save(str(full), deflate=True, garbage=4)
            sz = full.stat().st_size; print(f"ÍNTEGRA: {len(paths)} docs, {out.page_count} págs, {sz/1024/1024:.1f}MB", flush=True)
            # envia (divide se >45MB); SEI_SEM_TG=1 → só baixa/arquiva, sem Telegram
            if os.environ.get("SEI_SEM_TG") == "1":
                print("TG: pulado (SEI_SEM_TG=1)", flush=True)
                return
            LIM = 45 * 1024 * 1024
            if sz <= LIM:
                print("TG:", envia(str(full), f"📚 ÍNTEGRA COMPLETA — Processo SEI-{PROC} ({len(paths)} docs, {out.page_count} págs)"), flush=True)
            else:
                npart = sz // LIM + 1; per = (out.page_count // npart) + 1
                for k in range(0, out.page_count, per):
                    part = fitz.open(); part.insert_pdf(out, from_page=k, to_page=min(k + per - 1, out.page_count - 1))
                    pp = Path(f"data/sei_cache/INTEGRA_{TAG}_p{k//per+1}.pdf"); part.save(str(pp), deflate=True, garbage=4); part.close()
                    print(f"TG parte {k//per+1}:", envia(str(pp), f"📚 ÍNTEGRA SEI-{PROC} (parte {k//per+1}, págs {k+1}-{min(k+per,out.page_count)})"), flush=True)
        finally:
            await b.close()
    G.cleanup_orphans()


asyncio.run(main())
