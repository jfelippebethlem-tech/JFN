#!/usr/bin/env python
"""Resgata por OCR o teor dos documentos que só existem como IMAGEM.

Auditoria de 2026-07-23 sobre as 13.412 peças do cache:
    11.901 PDFs em BRANCO  (0 texto, 0 imagem) → o SEI nunca serviu o conteúdo;
       226 PDFs SÓ IMAGEM  (escaneado)         → teor existe, mas inanalisável;
     1.285 PDFs com texto real.

Os 226 escaneados são o único conteúdo que se perde de vista quando as peças
saem do cache: a imagem continua no PDF integral, mas nenhuma análise lê imagem.
Este script passa OCR neles e grava o teor no texto/*.txt do arquivo, marcando
`ocr: true` no manifesto. RODAR ANTES de enxugar o cache.

Ensaio por padrão; só grava com --aplicar.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "data" / "sei_cache"
ARQUIVO = RAIZ / "data" / "sei_arquivo"
sys.path.insert(0, str(RAIZ))

MIN_UTIL = 60          # abaixo disso o OCR não trouxe nada aproveitável


def _so_imagem(pdf: Path) -> bool:
    """PDF sem texto extraível mas COM imagem — escaneado de verdade."""
    import fitz
    try:
        d = fitz.open(str(pdf))
        texto = sum(len(pg.get_text().strip()) for pg in d)
        imgs = sum(len(pg.get_images()) for pg in d)
        d.close()
    except Exception:      # noqa: BLE001 — ilegível não é candidato
        return False
    return texto < 40 and imgs > 0


def resgatar(tag: str, aplicar: bool) -> list[dict]:
    marq = ARQUIVO / tag / "manifest.json"
    if not marq.exists():
        return []
    try:
        m = json.loads(marq.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    from compliance_agent.sei.ocr_docs import ocr_documento
    ganhos, mudou = [], False
    for d in (m.get("docs") or []):
        if (d.get("chars") or 0) >= MIN_UTIL or d.get("ocr"):
            continue
        pdf = CACHE / f"integra_{tag}" / f"{d['i']:03d}.pdf"
        if not pdf.exists() or not _so_imagem(pdf):
            continue
        try:
            texto = (ocr_documento(pdf.read_bytes(), tipo="pdf") or "").strip()
        except Exception as exc:      # noqa: BLE001 — OCR falho não derruba o resgate
            print(f"  {tag} doc {d['i']}: OCR falhou ({str(exc)[:50]})")
            continue
        if len(texto) < MIN_UTIL:
            continue
        ganhos.append({"tag": tag, "i": d["i"], "titulo": d.get("titulo", ""),
                       "chars": len(texto)})
        if aplicar:
            rel = d.get("texto") or f"texto/{d['i']:03d}_ocr.txt"
            (ARQUIVO / tag / rel).write_text(
                f"[{d.get('titulo','')}] (fase: {d.get('fase','')} · "
                f"tipo: {d.get('tipo','')}) [OCR]\n\n{texto}", encoding="utf-8")
            d["texto"], d["chars"], d["ocr"] = rel, len(texto), True
            mudou = True
    if mudou and aplicar:
        marq.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    return ganhos


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--max", type=int, default=0, help="limita processos (0 = todos)")
    a = ap.parse_args()
    todos, n = [], 0
    for d in sorted(CACHE.glob("integra_*")):
        if not d.is_dir():
            continue
        g = resgatar(d.name.replace("integra_", ""), a.aplicar)
        if g:
            n += 1
            todos += g
            print(f"  {d.name}: {len(g)} documentos resgatados "
                  f"({sum(x['chars'] for x in g)/1024:.0f} KB de teor)")
        if a.max and n >= a.max:
            break
    print(f"\n{len(todos)} documentos {'resgatados' if a.aplicar else 'resgatáveis'} "
          f"em {n} processos · {sum(x['chars'] for x in todos)/1024:.0f} KB de teor novo")
    if not a.aplicar:
        print("(ensaio — nada gravado; use --aplicar)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
