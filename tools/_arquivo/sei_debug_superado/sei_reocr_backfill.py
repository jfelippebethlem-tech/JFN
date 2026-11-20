# -*- coding: utf-8 -*-
"""Backfill de OCR dos processos já arquivados — re-leitura IN-SESSION.

Contexto: as libs de OCR (pytesseract/fitz/pdfminer) haviam sumido no rebuild do venv
ARM na migração → ``ocr_documento`` degradava para "" e o sweep NÃO OCR'ava scans. As
libs foram reinstaladas; os PDFs em cache dos docs ralos, porém, estão em branco/ausentes
(o conteúdo vivia no DOM do SEI). Logo a única forma de recuperar é RE-LER no SEI em
sessão (browser), agora com OCR funcional e o cap de docs alinhado ao caminho normal (40).

VM-safe: ``sei_reader.ler`` já serializa via ``browser_lock`` (nunca 2 browsers) e cede
sob load alto. Serial, bounded, degrada honesto (proc que falhar não derruba o resto).
"""
from __future__ import annotations

import asyncio
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import sei_reader  # noqa: E402

_ARQ = Path(__file__).resolve().parents[1] / "data" / "sei_arquivo"


def _procs_arquivados() -> list[str]:
    procs = []
    for mf in sorted(glob.glob(str(_ARQ / "*" / "manifest.json"))):
        try:
            procs.append(json.load(open(mf))["processo"])
        except Exception:
            continue
    return procs


async def _rodar(limite: int | None) -> None:
    procs = _procs_arquivados()[: limite or None]
    print(f"Backfill OCR in-session de {len(procs)} processos arquivados", flush=True)
    ok = ocr_docs = falhas = 0
    for i, proc in enumerate(procs, 1):
        try:
            res = await sei_reader.ler(proc, usar_cache=False)
        except Exception as exc:  # noqa: BLE001
            falhas += 1
            print(f"  [{i}/{len(procs)}] {proc}: ERRO {str(exc)[:80]}", flush=True)
            continue
        if res.get("erro") or res.get("indisponivel"):
            falhas += 1
            print(f"  [{i}/{len(procs)}] {proc}: {res.get('erro') or 'indisponivel'}", flush=True)
            continue
        docs = res.get("conteudo_documentos", [])
        n_ocr = sum(1 for d in docs if d.get("via") == "ocr")
        ok += 1
        ocr_docs += n_ocr
        print(f"  [{i}/{len(procs)}] {proc}: {len(docs)} docs lidos, {n_ocr} via OCR", flush=True)
    print(f"\nRESUMO BACKFILL: ok={ok} falhas={falhas} docs_via_ocr={ocr_docs}", flush=True)


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(_rodar(lim))
