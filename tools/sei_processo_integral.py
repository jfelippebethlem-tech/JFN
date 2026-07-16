#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Íntegra de UM processo SEI (TODA a instrução, cross-unit), RESILIENTE a processos GRANDES.

Por que resiliente (2026-07-14): em processos de centenas de docs o chromium acumula memória ao longo
dos cliques e o renderer CAI ("Target page/context/browser closed"); sem timeout nos awaits, o python
PENDURA. Fix: (1) lê em LOTES relançando o browser a cada SEI_BATCH docs (memória sempre limitada);
(2) CHECKPOINT por doc em data/sei_cache/resume_<tag>.json (crash/relançamento NÃO recomeça do zero —
retoma de onde parou); (3) TIMEOUT por doc e por carga de árvore (nunca pendura); (4) relança e retoma
ao detectar browser morto. Usa os primitivos canônicos do sei_reader (login itkava + _ler_cracked +
_conteudo_via_arvore). Renderiza PDF com 1 marcador por documento = índice clicável.

Uso: SEI_MAX_DOCS=500 .venv/bin/python tools/sei_processo_integral.py "070028/000089/2021" saida.pdf
Env: SEI_MAX_DOCS (default 500) · SEI_BATCH (docs por sessão de browser, default 40) ·
     SEI_DOC_TIMEOUT (s por doc, default 60) · SEI_ARVORE_TIMEOUT (s p/ carregar a árvore, default 150) ·
     SEI_MAX_RELAUNCH (relançamentos máx., default 40) · SEI_SEM_TG (não usado aqui).
"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path

import fitz

sys.path.insert(0, "/home/ubuntu/JFN")
from tools import sei_reader as SR  # noqa: E402
from tools import vm_guard as G  # noqa: E402
from playwright.async_api import async_playwright, Error as PWError  # noqa: E402
import logging

logger = logging.getLogger(__name__)

PROC = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else f"data/proc_integra/{re.sub(r'[^0-9]', '_', PROC)}.pdf"
TAG = re.sub(r"[^0-9A-Za-z]", "_", PROC)
MAX_DOCS = int(os.environ.get("SEI_MAX_DOCS", "500"))
BATCH = int(os.environ.get("SEI_BATCH", "200"))  # relançamento preventivo raro (válvula de memória);
DOC_TIMEOUT = int(os.environ.get("SEI_DOC_TIMEOUT", "60"))
ARVORE_TIMEOUT = int(os.environ.get("SEI_ARVORE_TIMEOUT", "150"))
MAX_RELAUNCH = int(os.environ.get("SEI_MAX_RELAUNCH", "40"))
RESUME = Path(f"data/sei_cache/resume_{TAG}.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _load_ckpt() -> dict:
    if RESUME.exists():
        try:
            return json.loads(RESUME.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.debug("resume ilegível — recomeçando do zero")
    return {"numero": PROC, "docs": [], "conteudos": {}}


def _save_ckpt(ck: dict) -> None:
    RESUME.parent.mkdir(parents=True, exist_ok=True)
    tmp = RESUME.with_suffix(".tmp")
    tmp.write_text(json.dumps(ck, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, RESUME)


async def _novo_browser(pw):
    b = await pw.chromium.launch(headless=True, args=G.guarded_launch_args())
    ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR", user_agent=UA)
    pg = await ctx.new_page()
    await pg.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    if not await SR.login(pg, tentativas=25):
        await b.close()
        return None, None
    return b, pg


async def _abrir_arvore(pg):
    """Carrega a árvore (com timeout + retry) e devolve a lista de docs. [] se não abrir."""
    for _ in range(3):
        try:
            dump = await asyncio.wait_for(SR._ler_cracked(pg, PROC), timeout=ARVORE_TIMEOUT)
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001
            dump = {}
        docs = (dump or {}).get("documentos") or []
        if docs:
            return docs
        try:
            await pg.wait_for_timeout(2500)
        except PWError:
            break
    return []


def _idd(d: dict) -> str | None:
    m = re.search(r"id_documento=(\d+)", d.get("url") or "")
    return m.group(1) if m else None


async def _coletar():
    """Loop resiliente: lê os docs em lotes, relançando o browser e retomando do checkpoint."""
    G.cleanup_orphans()
    ck = _load_ckpt()
    relaunches = 0
    async with async_playwright() as pw:
        while relaunches <= MAX_RELAUNCH:
            ok, _m = G.preflight()
            if not ok:
                G.wait_until_safe(120)
            b = pg = None
            try:
                b, pg = await _novo_browser(pw)
                if not pg:
                    print("LOGIN FALHOU", flush=True); relaunches += 1; continue
                docs = await _abrir_arvore(pg)
                if not docs:
                    print("SEM ÁRVORE (tentativa)", flush=True); relaunches += 1
                    try: await b.close()
                    except PWError as exc:
                        logger.debug("close do browser falhou: %s", exc)
                    continue
                if not ck["docs"]:
                    ck["docs"] = [{"titulo": d.get("titulo") or d.get("texto") or "", "url": d.get("url") or "",
                                   "idd": _idd(d)} for d in docs]
                    _save_ckpt(ck)
                alvo = ck["docs"][:MAX_DOCS]
                pendentes = [d for d in alvo if d.get("idd") and d["idd"] not in ck["conteudos"]]
                print(f"árvore: {len(docs)} docs | já lidos: {len(ck['conteudos'])} | pendentes: {len(pendentes)}", flush=True)
                if not pendentes:
                    try: await b.close()
                    except PWError as exc:
                        logger.debug("close do browser falhou: %s", exc)
                    break
                lidos_no_lote = 0
                crashou = False
                for d in pendentes:
                    try:
                        c = await asyncio.wait_for(
                            SR._conteudo_via_arvore(pg, {"url": d["url"], "texto": d["titulo"]}),
                            timeout=DOC_TIMEOUT)
                    except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
                        msg = str(e).lower()
                        if "closed" in msg or "crash" in msg or isinstance(e, asyncio.TimeoutError):
                            # browser morreu/pendurou NESTE doc: marca-o como PULADO (anti "doc-veneno" —
                            # senão ele derrubaria o browser a cada retomada e travaria o progresso) e relança.
                            ck["conteudos"][d["idd"]] = {"doc": d["titulo"][:80], "conteudo": "",
                                                         "via": None, "pulado": "browser caiu neste doc"}
                            _save_ckpt(ck)
                            crashou = True; break
                        c = None                            # erro pontual do doc → segue
                    if c and (c.get("conteudo") or "").strip():
                        ck["conteudos"][d["idd"]] = {"doc": c.get("doc") or d["titulo"][:80],
                                                     "conteudo": c["conteudo"], "via": c.get("via")}
                    else:
                        ck["conteudos"][d["idd"]] = {"doc": d["titulo"][:80], "conteudo": "", "via": None}
                    lidos_no_lote += 1
                    if lidos_no_lote % 10 == 0:
                        _save_ckpt(ck)
                        print(f"  {len(ck['conteudos'])}/{len(alvo)} (lote {lidos_no_lote}/{BATCH})", flush=True)
                    if lidos_no_lote >= BATCH:
                        break                               # relança preventivo (memória limitada)
                _save_ckpt(ck)
                try: await b.close()
                except PWError as exc:
                    logger.debug("close do browser falhou: %s", exc)
                if crashou:
                    relaunches += 1
                    print(f"  browser caiu/pendurou — relançando ({relaunches}/{MAX_RELAUNCH}) e retomando", flush=True)
                # senão: lote OK, laço continua com novo browser (relançamento preventivo, sem custar relaunch)
                if len([d for d in alvo if d.get("idd") and d["idd"] not in ck["conteudos"]]) == 0:
                    break
            except Exception as e:  # noqa: BLE001
                print(f"  erro de sessão: {str(e)[:80]} — relançando", flush=True)
                relaunches += 1
                try:
                    if b: await b.close()
                except PWError as exc:
                    logger.debug("close do browser falhou: %s", exc)
            finally:
                G.cleanup_orphans()
    return ck


def _pdf(ck: dict) -> fitz.Document:
    docs = ck["docs"][:MAX_DOCS]
    out = fitz.open()
    cap = out.new_page()
    cap.insert_text((60, 120), f"PROCESSO SEI-{PROC}", fontsize=15)
    com = sum(1 for d in docs if (ck["conteudos"].get(d.get("idd") or "", {}).get("conteudo") or "").strip())
    cap.insert_text((60, 150), f"{len(docs)} documentos — instrução completa ({com} com texto)", fontsize=11)
    toc = [[1, f"Processo SEI-{PROC}", 1]]
    for i, d in enumerate(docs, 1):
        titulo = (d.get("titulo") or f"Documento {i}").strip()
        txt = (ck["conteudos"].get(d.get("idd") or "", {}).get("conteudo") or "").strip()
        pno = out.page_count + 1
        p = out.new_page()
        p.insert_textbox(fitz.Rect(40, 36, 555, 62), f"[{i:03d}] {titulo}", fontsize=9, color=(0.48, 0.12, 0.12))
        body = txt if txt else "(documento sem texto extraível — provável imagem/anexo; consta da árvore)"
        p.insert_textbox(fitz.Rect(40, 68, 555, 800), body[:5600], fontsize=8)
        rest = body[5600:]
        while rest:
            pp = out.new_page(); pp.insert_textbox(fitz.Rect(40, 40, 555, 800), rest[:6200], fontsize=8); rest = rest[6200:]
        toc.append([2, f"[{i:03d}] {titulo[:64]}", pno])
    out.set_toc(toc)
    return out


async def main():
    ck = await _coletar()
    docs = ck["docs"][:MAX_DOCS]
    if not docs:
        print("SEM ÁRVORE (nenhum doc após relançamentos)"); return 1
    com = sum(1 for d in docs if (ck["conteudos"].get(d.get("idd") or "", {}).get("conteudo") or "").strip())
    Path(OUT).parent.mkdir(parents=True, exist_ok=True)
    out = _pdf(ck)
    out.save(OUT, deflate=True, garbage=4)
    print(f"OK: {OUT} · {out.page_count} págs · {len(docs)} docs · {com} com texto")
    # limpa o checkpoint só se leu tudo (senão preserva p/ retomar depois)
    pend = [d for d in docs if d.get("idd") and d["idd"] not in ck["conteudos"]]
    if not pend:
        try: RESUME.unlink()
        except OSError as exc:
            logger.debug("unlink do resume falhou: %s", exc)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
