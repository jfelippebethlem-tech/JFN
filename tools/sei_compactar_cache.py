#!/usr/bin/env python
"""Enxuga o cache do SEI sem perder NADA do processo.

Medição de 2026-07-23 (data/sei_cache = 1,5 GB):

  INTEGRA_<proc>.pdf   358 arq · 0,58 GB → o PROCESSO NA ÍNTEGRA. **Nunca tocar.**
  integra_<proc>/NNN.pdf 13.412 arq · 524 MB → peças soltas, das quais o PDF integral
                        foi montado e cujo teor já está extraído em texto/*.txt.
                        Redundância tripla: PDF integral + texto + peça solta.
  sei_arquivo/texto/*.txt  26 MB → o que toda análise realmente lê.

Este script apaga SOMENTE as peças soltas, e só quando as três garantias valem
para aquele processo:
  1. existe o INTEGRA_<proc>.pdf consolidado (o processo inteiro está guardado);
  2. existe texto extraído em data/sei_arquivo/<proc>/texto/*.txt;
  3. a captura está declarada COMPLETA (manifesto novo `completo: true`) ou o
     processo já foi arquivado com documentos — nunca mexe em download em curso,
     porque a retomada usa justamente essas peças para não rebaixar o que já veio.

Ensaio por padrão. Só apaga com --aplicar.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "data" / "sei_cache"
ARQUIVO = RAIZ / "data" / "sei_arquivo"


def _paginas(pdf: Path) -> int:
    """Nº de páginas, ou -1 se ilegível (não confiar em PDF que não abre)."""
    try:
        import fitz
        d = fitz.open(str(pdf))
        n = d.page_count
        d.close()
        return n
    except (RuntimeError, ValueError, OSError, TypeError):
        return -1      # PDF que não abre não é contabilizável


def _integral_cobre(tag: str, pecas: list[Path]) -> tuple[bool, str]:
    """O PDF integral tem de conter TODAS as páginas das peças.

    Existir não basta: se o processo foi rebaixado depois e o integral não foi
    remontado, ele está DESATUALIZADO e apagar as peças perderia documento.
    O integral traz 1 página de separador a mais — por isso o >= puro.
    """
    soma = 0
    for p in pecas:
        n = _paginas(p)
        if n < 0:
            return False, "peça ilegível (não arrisco)"
        soma += n
    n_int = _paginas(CACHE / f"INTEGRA_{tag}.pdf")
    if n_int < 0:
        return False, "PDF integral ilegível"
    if n_int < soma:
        return False, f"integral DESATUALIZADO ({n_int} pgs < {soma} das peças)"
    return True, ""


def _seguro(tag: str, pecas: list[Path] | None = None) -> tuple[bool, str]:
    if not (CACHE / f"INTEGRA_{tag}.pdf").exists():
        return False, "sem PDF integral consolidado"
    dir_txt = ARQUIVO / tag / "texto"
    if not dir_txt.is_dir() or not any(dir_txt.glob("*.txt")):
        return False, "sem texto extraído"
    mcache = CACHE / f"integra_{tag}" / "manifest.json"
    if mcache.exists():
        try:
            bruto = json.loads(mcache.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False, "manifesto do cache ilegível"
        if isinstance(bruto, dict) and not bruto.get("completo"):
            return False, "captura em curso/parcial (retomada precisa das peças)"
    marq = ARQUIVO / tag / "manifest.json"
    if not marq.exists():
        return False, "sem manifesto de arquivo"
    try:
        if not (json.loads(marq.read_text(encoding="utf-8")).get("docs") or []):
            return False, "arquivo sem documentos"
    except (ValueError, OSError):
        return False, "manifesto de arquivo ilegível"
    if pecas:                       # 4ª garantia: conferir PÁGINA A PÁGINA, não só existir
        return _integral_cobre(tag, pecas)
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true", help="apaga de fato (sem isso, só relata)")
    a = ap.parse_args()
    libera = mantem = 0
    n_ok = 0
    motivos: dict[str, int] = {}
    for d in sorted(CACHE.glob("integra_*")):
        if not d.is_dir():
            continue
        tag = d.name.replace("integra_", "")
        pecas = sorted(d.glob("[0-9][0-9][0-9]*.pdf"))
        if not pecas:
            continue
        peso = sum(p.stat().st_size for p in pecas)
        ok, motivo = _seguro(tag, pecas)
        if not ok:
            mantem += peso
            motivos[motivo] = motivos.get(motivo, 0) + 1
            continue
        n_ok += 1
        libera += peso
        if a.aplicar:
            for p in pecas:
                p.unlink(missing_ok=True)
    print(f"processos enxugáveis : {n_ok}")
    print(f"espaço {'liberado' if a.aplicar else 'liberável'} : {libera/1048576:.0f} MB")
    print(f"mantido por segurança : {mantem/1048576:.0f} MB")
    for m, n in sorted(motivos.items(), key=lambda x: -x[1]):
        print(f"   {n:4d} processos — {m}")
    if not a.aplicar:
        print("\n(ensaio — nada foi apagado; use --aplicar)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
