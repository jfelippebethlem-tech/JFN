#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pagina um processo SEI, BAIXA cada documento-alvo (PDF), ENVIA ao Telegram do dono e OCR'a.
Guardado (vm_guard). Uso:
  SEI_OCR_DOCS=12 .venv/bin/python tools/sei_docs_to_telegram.py "330020/000762/2021" "termo|planilha|parecer|cota|proposta|anexo"
"""
import os, sys, re, json, asyncio
from pathlib import Path
sys.path.insert(0, "/home/ubuntu/JFN")
from tools import sei_reader as SR
from tools import vm_guard as G
from tools.sei_proc_paginado import docs_da_pagina, clicar_proxima
from playwright.async_api import async_playwright
import httpx

PROC = sys.argv[1]
KW = sys.argv[2] if len(sys.argv) > 2 else r"termo|planilha|parecer|cota|proposta|anexo|atestado|nota fiscal|edital|contrato|reequil"
MAXN = int(os.environ.get("SEI_OCR_DOCS", "12"))
MAX_PAG = int(os.environ.get("SEI_MAX_PAG", "20"))
TAG = re.sub(r"[^0-9]", "_", PROC)
ENV = Path("/home/ubuntu/.hermes/.env")
def _k(n):
    m = re.search(rf"^{n}=(.+)$", ENV.read_text(), re.M); return m.group(1).strip().strip('"').strip("'") if m else ""
TOK, CHAT = _k("TELEGRAM_BOT_TOKEN"), _k("TELEGRAM_CHAT_ID"); TB = f"https://api.telegram.org/bot{TOK}"


def envia_tg(path, caption):
    try:
        with open(path, "rb") as f:
            r = httpx.post(f"{TB}/sendDocument", data={"chat_id": CHAT, "caption": caption[:1000]},
                           files={"document": (Path(path).name, f, "application/pdf")}, timeout=120)
        return r.json().get("ok")
    except Exception as e:
        print("  TG erro:", str(e)[:60], flush=True); return False


async def main():
    G.cleanup_orphans()
    ok, m = G.preflight()
    print("PREFLIGHT:", ok, m, flush=True)
    if not ok:
        ok, m = G.wait_until_safe(150)
        if not ok: return
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=G.guarded_launch_args())
        ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        pg = await ctx.new_page(); await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        try:
            if not await SR.login(pg, tentativas=25): print("LOGIN FALHOU"); return
            print("login OK", flush=True)
            try: await SR._ler_cracked(pg, PROC)
            except Exception as e: print("crk", str(e)[:40], flush=True)
            await pg.wait_for_timeout(2000)
            todos = {}; zero = 0
            for p in range(1, MAX_PAG + 1):
                d = await docs_da_pagina(pg); nv = {u: v for u, v in d.items() if u not in todos}; todos.update(d)
                zero = zero + 1 if not nv else 0
                if zero >= 3: break
                if not await clicar_proxima(pg, p * 10): break
                await pg.wait_for_timeout(3200)
            docs = list(todos.values())
            alvo = [x for x in docs if re.search(KW, (x["t"] + " " + x["pai"]), re.I) and not re.search(r"despacho de encaminhamento|cancelamento|e-mail|of[íi]cio|registro siaf", x["t"], re.I)]
            print(f"TOTAL {len(docs)} docs; {len(alvo)} alvos p/ baixar+enviar", flush=True)
            from compliance_agent.sei.ocr_docs import ocr_documento
            outdir = Path(f"data/sei_cache/docs_{TAG}"); outdir.mkdir(parents=True, exist_ok=True)
            feitos = 0
            for x in alvo:
                if feitos >= MAXN: print(f"[limite {MAXN}; restam {len(alvo)-feitos}]", flush=True); break
                try:
                    resp = await ctx.request.get(x["u"], timeout=45000); body = await resp.body()
                    ct = (resp.headers.get("content-type") or "").lower()
                    titulo = re.sub(r"[^0-9A-Za-zçãõéêíóáÁ -]", "", x["t"])[:45].strip() or "doc"
                    nome = re.sub(r"[^0-9A-Za-z]", "_", titulo)[:40]
                    if "pdf" in ct or body[:5] == b"%PDF-":
                        fp = outdir / f"{feitos:02d}_{nome}.pdf"; fp.write_bytes(body)
                        okt = envia_tg(str(fp), f"[{PROC}] {x['t']}")
                        txt = await asyncio.get_event_loop().run_in_executor(None, lambda: ocr_documento(body, tipo="pdf") or "")
                        (outdir / f"{feitos:02d}_{nome}.txt").write_text(txt)
                        # valores R$ relevantes
                        vals = sorted(set(re.findall(r"\d{1,3}\.\d{3},\d{2}|1\.?\d{3}\.\d{3},\d{2}", txt)))
                        print(f"  [{feitos}] '{x['t'][:40]}' PDF {len(body)//1024}KB → TG={okt} | R$: {vals[:6]}", flush=True)
                        feitos += 1
                    else:
                        # doc NATIVO (HTML): renderiza a página do documento em PDF e envia
                        try:
                            dp = await ctx.new_page()
                            await dp.goto(x["u"], wait_until="networkidle", timeout=40000)
                            await dp.wait_for_timeout(1500)
                            fp = outdir / f"{feitos:02d}_{nome}.pdf"
                            await dp.pdf(path=str(fp), format="A4", print_background=True)
                            await dp.close()
                            okt = envia_tg(str(fp), f"[{PROC}] {x['t']}")
                            txt = await SR._conteudo_doc(pg, x) if False else ""
                            t2 = ""
                            try:
                                t2 = (await (await ctx.request.get(x["u"], timeout=30000)).text())
                            except Exception:
                                pass
                            (outdir / f"{feitos:02d}_{nome}.txt").write_text(re.sub(r"<[^>]+>", " ", t2)[:8000])
                            print(f"  [{feitos}] '{x['t'][:40]}' HTML→PDF → TG={okt}", flush=True)
                            feitos += 1
                        except Exception as e:
                            print(f"  [HTML render erro] '{x['t'][:30]}': {str(e)[:50]}", flush=True)
                except Exception as e:
                    print(f"  erro '{x['t'][:30]}': {str(e)[:50]}", flush=True)
            # aviso final ao dono
            httpx.post(f"{TB}/sendMessage", data={"chat_id": CHAT, "text": f"📎 {feitos} documentos primários do processo {PROC} enviados (planilhas/termos/pareceres/cotações)."}, timeout=30)
        finally:
            await b.close()
    G.cleanup_orphans()


asyncio.run(main())
