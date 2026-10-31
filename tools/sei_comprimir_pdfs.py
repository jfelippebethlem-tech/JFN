#!/usr/bin/env python
"""Encolhe os PDFs do cache do SEI reamostrando as imagens para 150 dpi (Ghostscript /ebook).

Pedido do dono em 30/10/2026: os ~20 GB de PDF em `data/sei_cache` precisam ficar muito mais leves.
Medido na amostra: PDF escaneado cai 2,6–3,7×, com as mesmas páginas e o mesmo texto extraível.
É compressão COM PERDA nas imagens — 150 dpi mantém o documento legível e a foto comparável
(o pHash trabalha em 32×32), mas não é o original byte a byte.

Só troca o arquivo quando TODAS as garantias valem, senão o original fica:
  1. mesmo número de páginas;
  2. texto extraível preservado (≥ 99% dos caracteres nas páginas amostradas);
  3. o novo tem no máximo 80% do tamanho do original.
Nunca toca `_truncados/` (o reparo os rebaixa) nem arquivo mexido há menos de 3 dias (captura em curso).
Um arquivo por vez, com nice e teto de tempo por arquivo. Ensaio por padrão; só grava com --aplicar.
Registro de cada troca em `data/sei_comprimir_pdfs.jsonl`.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "data" / "sei_cache"
REGISTRO = RAIZ / "data" / "sei_comprimir_pdfs.jsonl"
MIN_MB = 1.0
IDADE_MIN_S = 3 * 86400
FATOR_MAX = 0.8
TEXTO_MIN = 0.99
TETO_S = 2400


def candidatos(cache: Path = CACHE, min_mb: float = MIN_MB, agora: float | None = None) -> list[Path]:
    """PDFs elegíveis, do maior para o menor."""
    agora = agora or time.time()
    itens = []
    for p in cache.rglob("*.pdf"):
        if "_truncados" in p.relative_to(cache).parts:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size >= min_mb * 1e6 and agora - st.st_mtime >= IDADE_MIN_S:
            itens.append((st.st_size, p))
    return [p for _, p in sorted(itens, key=lambda t: -t[0])]


def _perfil(pdf: Path) -> tuple[int, int]:
    """(páginas, caracteres de texto numa amostra de ~20 páginas). (-1, 0) se não abre."""
    import fitz
    try:
        d = fitz.open(str(pdf))
    except (RuntimeError, ValueError, OSError):
        return -1, 0
    try:
        n = d.page_count
        passo = max(1, n // 20)
        return n, sum(len(d[i].get_text()) for i in range(0, n, passo))
    finally:
        d.close()


def comprimir(pdf: Path, aplicar: bool, teto_s: int = TETO_S) -> dict:
    antes = pdf.stat().st_size
    base = {"arquivo": str(pdf.relative_to(CACHE)) if pdf.is_relative_to(CACHE) else pdf.name,
            "mb_antes": round(antes / 1e6, 2)}
    tmp = pdf.with_name(pdf.name + ".gs.tmp")
    try:
        try:
            subprocess.run(["nice", "-n", "15", "gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite",
                            "-dCompatibilityLevel=1.6", "-dPDFSETTINGS=/ebook", "-dDetectDuplicateImages=true",
                            f"-sOutputFile={tmp}", str(pdf)], capture_output=True, timeout=teto_s, check=True)
        except subprocess.TimeoutExpired:
            return {**base, "mantido": f"Ghostscript passou de {teto_s} s"}
        except (OSError, subprocess.CalledProcessError) as e:
            return {**base, "mantido": f"Ghostscript falhou ({str(e)[:60]})"}
        depois = tmp.stat().st_size
        base["mb_depois"] = round(depois / 1e6, 2)
        if depois > antes * FATOR_MAX:
            return {**base, "mantido": "ganho menor que 20%"}
        (pa, ta), (pb, tb) = _perfil(pdf), _perfil(tmp)
        if pa < 0 or pb != pa:
            return {**base, "mantido": f"páginas não conferem ({pa} → {pb})"}
        if ta and tb < ta * TEXTO_MIN:
            return {**base, "mantido": f"texto caiu ({ta} → {tb} caracteres na amostra)"}
        if not aplicar:
            return {**base, "trocaria": True}
        mtime = pdf.stat().st_mtime
        tmp.replace(pdf)
        os.utime(pdf, (mtime, mtime))          # a idade do arquivo é a da captura, não a da compressão
        return {**base, "trocado": True, "paginas": pa}
    finally:
        tmp.unlink(missing_ok=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--max", type=int, default=0, help="quantos arquivos nesta rodada (0 = todos)")
    ap.add_argument("--min-mb", type=float, default=MIN_MB)
    ap.add_argument("--carga-max", type=float, default=4.0, help="espera a carga baixar antes de cada arquivo")
    a = ap.parse_args(argv)
    alvos = candidatos(min_mb=a.min_mb)
    if a.max:
        alvos = alvos[:a.max]
    print(f"PDFs elegíveis: {len(alvos)} · {sum(p.stat().st_size for p in alvos) / 1e9:.2f} GB", flush=True)
    ganho = 0
    for p in alvos:
        while os.getloadavg()[0] >= a.carga_max:
            time.sleep(60)
        r = comprimir(p, a.aplicar)
        if r.get("trocado"):
            ganho += (r["mb_antes"] - r["mb_depois"])
            with REGISTRO.open("a", encoding="utf-8") as f:
                f.write(json.dumps({**r, "em": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                                   ensure_ascii=False) + "\n")
        print(f"  {r['arquivo']}: {r['mb_antes']} → {r.get('mb_depois', '—')} MB · "
              f"{'trocado' if r.get('trocado') else 'trocaria' if r.get('trocaria') else r.get('mantido')}", flush=True)
    print(f"\nliberado: {ganho / 1e3:.2f} GB{'' if a.aplicar else '  (ENSAIO — use --aplicar)'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
