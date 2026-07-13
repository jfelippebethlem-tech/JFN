#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Íntegra de um processo SEI (TODA a instrução, cross-unit) via o ler() canônico — que gerencia o
próprio browser e extrai o CONTEÚDO de cada documento (drill no iframe + OCR). Renderiza um PDF com
UMA marcação (bookmark) por documento = índice clicável da instrução inteira. Eleva SEI_MAX_DOCS para
pegar todos os documentos (o default do ler() é 40).

Uso: SEI_MAX_DOCS=400 .venv/bin/python tools/sei_processo_integral.py "070002/004135/2025" saida.pdf
"""
import asyncio
import os
import re
import sys
from pathlib import Path

import fitz

sys.path.insert(0, "/home/ubuntu/JFN")
from tools import sei_reader as SR  # noqa: E402

PROC = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else f"data/proc_integra/{re.sub(r'[^0-9]', '_', PROC)}.pdf"
os.environ.setdefault("SEI_MAX_DOCS", "500")   # sem isto o ler() para em 40 docs


def _pdf_dos_docs(numero: str, docs: list, conteudos: list) -> fitz.Document:
    """Monta o PDF: capa + 1 doc por seção, com bookmark (nível 2) por documento = índice clicável."""
    by_title = {}
    for c in conteudos:
        by_title.setdefault((c.get("doc") or "")[:60], c.get("conteudo") or "")
    out = fitz.open()
    cap = out.new_page()
    cap.insert_text((60, 120), f"PROCESSO SEI-{numero}", fontsize=15)
    cap.insert_text((60, 150), f"{len(docs)} documentos — instrução completa", fontsize=11)
    toc = [[1, f"Processo SEI-{numero}", 1]]
    for i, d in enumerate(docs, 1):
        titulo = (d.get("titulo") or d.get("texto") or f"Documento {i}").strip()
        txt = by_title.get(titulo[:60], "")
        pno = out.page_count + 1
        p = out.new_page()
        p.insert_textbox(fitz.Rect(40, 36, 555, 62), f"[{i:03d}] {titulo}", fontsize=9, color=(0.48, 0.12, 0.12))
        body = txt if txt.strip() else "(documento sem texto extraível — provável imagem/anexo; consta da árvore)"
        p.insert_textbox(fitz.Rect(40, 68, 555, 800), body[:5600], fontsize=8)
        rest = body[5600:]
        while rest:
            p2 = out.new_page(); p2.insert_textbox(fitz.Rect(40, 40, 555, 800), rest[:6200], fontsize=8); rest = rest[6200:]
        toc.append([2, f"[{i:03d}] {titulo[:64]}", pno])
    out.set_toc(toc)
    return out


async def main():
    r = await SR.ler(PROC, usar_cache=False)
    if r.get("erro"):
        print(f"ERRO: {r['erro']}")
        return 1
    docs = r.get("documentos") or []
    conteudos = r.get("conteudo_documentos") or []
    print(f"docs na árvore: {len(docs)} | conteúdos extraídos: {len(conteudos)}", flush=True)
    if not docs:
        print("SEM ÁRVORE")
        return 1
    Path(OUT).parent.mkdir(parents=True, exist_ok=True)
    out = _pdf_dos_docs(PROC, docs, conteudos)
    out.save(OUT, deflate=True, garbage=4)
    com = sum(1 for c in conteudos if (c.get("conteudo") or "").strip())
    print(f"OK: {OUT} · {out.page_count} págs · {len(docs)} docs · {com} com texto")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
