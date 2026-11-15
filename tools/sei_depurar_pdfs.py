#!/usr/bin/env python
"""Depura os PDFs soltos das íntegras do SEI (`data/sei_cache/integra_<proc>/NNN.pdf`) para ocupar menos disco.

Pedido do dono (15/11/2026, disco da VM-1 em 100%): "precisa depurar esses pdfs e colocar em um tipo de arquivo que
ocupe menos espaço". Medido no mesmo dia: 64.689 PDFs, 61,7 GB, 21,8 GB chegando a cada 6 h pelas sessões do
it-campo. Recomprimir imagem ganhou só ~4% numa amostra de 12 — a maioria é documento NATIVO do SEI (texto puro).

Duas regras, por documento:
  1. NATIVO (toda página com camada de texto, nenhuma imagem acima de 15% da página) → o PDF sai e fica
     `NNN.txt` com o texto do PRÓPRIO PDF, e um registro em `depurados.json` com sha256, bytes, páginas e a URL
     do documento no SEI (o original continua lá; o sha256 prova a identidade se for baixado de novo).
  2. ESCANEADO / COM IMAGEM → o PDF fica; é recomprimido (imagens a 150 dpi, PyMuPDF) só se o novo tiver
     ≤ 80% do tamanho, o MESMO número de páginas e ≥ 99% do texto extraível.

Nunca mexe em pasta com arquivo alterado há menos de `--idade-min-h` (captura em curso), nem em `_truncados/`.
Com `--exigir-arquivo`, só mexe se o arquivamento do processo (`sei_arquivo/<tag>/manifest.json`) já existe — o
arquivador lê estes PDFs. Ensaio por padrão; só grava com --aplicar.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "data" / "sei_cache"
ARQUIVO = RAIZ / "data" / "sei_arquivo"
REGISTRO = "depurados.json"
IMAGEM_MAX = 0.15          # fração da página que uma imagem pode cobrir num documento "nativo"
TEXTO_MIN_PAGINA = 20      # caracteres mínimos por página para contar como camada de texto
FATOR_MAX = 0.8
TEXTO_MIN = 0.99


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def classificar(pdf: Path) -> tuple[str, str, int]:
    """('nativo' | 'imagem' | 'ilegivel', texto, páginas)."""
    import fitz
    try:
        d = fitz.open(str(pdf))
    except (RuntimeError, ValueError, OSError):
        return "ilegivel", "", -1
    try:
        n = d.page_count
        if n == 0:
            return "ilegivel", "", 0
        partes, nativo = [], True
        for pg in d:
            t = pg.get_text()
            partes.append(t)
            if len(t.strip()) < TEXTO_MIN_PAGINA:
                nativo = False
            area = abs(pg.rect) or 1.0
            for img in pg.get_image_info():
                if abs(fitz.Rect(img["bbox"]) & pg.rect) > IMAGEM_MAX * area:
                    nativo = False
                    break
        return ("nativo" if nativo else "imagem"), "\f".join(partes), n
    finally:
        d.close()


def _texto_total(pdf: Path) -> tuple[int, int]:
    import fitz
    try:
        d = fitz.open(str(pdf))
    except (RuntimeError, ValueError, OSError):
        return -1, 0
    try:
        return d.page_count, sum(len(pg.get_text()) for pg in d)
    finally:
        d.close()


def recomprimir(pdf: Path, aplicar: bool) -> int:
    """Bytes ganhos (0 se mantido)."""
    import fitz
    antes = pdf.stat().st_size
    tmp = pdf.with_name(pdf.name + ".mu.tmp")
    try:
        try:
            d = fitz.open(str(pdf))
            d.rewrite_images(dpi_threshold=160, dpi_target=150, quality=75)
            d.save(str(tmp), garbage=3, deflate=True, deflate_images=True, deflate_fonts=True, use_objstms=1)
            d.close()
        except (RuntimeError, ValueError, OSError):
            return 0
        depois = tmp.stat().st_size
        if depois > antes * FATOR_MAX:
            return 0
        (pa, ta), (pb, tb) = _texto_total(pdf), _texto_total(tmp)
        if pa < 0 or pb != pa or (ta and tb < ta * TEXTO_MIN):
            return 0
        if aplicar:
            mtime = pdf.stat().st_mtime
            tmp.replace(pdf)
            os.utime(pdf, (mtime, mtime))
        return antes - depois
    finally:
        tmp.unlink(missing_ok=True)


def _urls(pasta: Path) -> dict[str, str]:
    try:
        m = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {d.get("arquivo", ""): d.get("url", "") for d in (m.get("docs") or []) if isinstance(d, dict)}


def depurar_pasta(pasta: Path, aplicar: bool = False, recomprimir_imagem: bool = True) -> dict:
    reg_p = pasta / REGISTRO
    try:
        reg = json.loads(reg_p.read_text(encoding="utf-8")) if reg_p.exists() else {}
    except (OSError, ValueError):
        return {"pasta": pasta.name, "erro": "depurados.json ilegível — não mexo"}
    urls = _urls(pasta)
    out = {"pasta": pasta.name, "nativos": 0, "imagem": 0, "ilegiveis": 0, "bytes_liberados": 0}
    for pdf in sorted(pasta.glob("[0-9][0-9][0-9]*.pdf")):
        tipo, texto, n = classificar(pdf)
        if tipo == "nativo":
            antes = pdf.stat().st_size
            item = {"sha256": _sha256(pdf), "bytes": antes, "paginas": n, "chars": len(texto),
                    "url": urls.get(pdf.name, ""), "em": time.strftime("%F %T")}
            out["nativos"] += 1
            if aplicar:
                txt = pdf.with_suffix(".txt")
                tmp = txt.with_name(txt.name + ".tmp")
                tmp.write_text(texto, encoding="utf-8")
                if tmp.read_text(encoding="utf-8") != texto:        # releitura: só apaga com o texto gravado
                    tmp.unlink(missing_ok=True)
                    continue
                tmp.replace(txt)
                reg[pdf.name] = item
                tmp_reg = reg_p.with_name(REGISTRO + ".tmp")
                tmp_reg.write_text(json.dumps(reg, ensure_ascii=False, indent=0), encoding="utf-8")
                tmp_reg.replace(reg_p)                               # registro gravado ANTES de o PDF sair
                # herdam a data do PDF: o arquivador rearquiva a pasta se algum arquivo ficar mais novo
                # que o manifesto dele (sei_arquivar.arquivar_pendentes)
                mtime = pdf.stat().st_mtime
                for f in (txt, reg_p):
                    os.utime(f, (mtime, mtime))
                pdf.unlink()
            out["bytes_liberados"] += antes - len(texto.encode("utf-8"))
        elif tipo == "imagem":
            out["imagem"] += 1
            if recomprimir_imagem:
                out["bytes_liberados"] += recomprimir(pdf, aplicar)
        else:
            out["ilegiveis"] += 1
    return out


def pastas_elegiveis(cache: Path, idade_min_h: float, arquivo: Path | None, agora: float | None = None) -> list[Path]:
    agora = agora or time.time()
    res = []
    for d in sorted(cache.glob("integra_*")):
        if not d.is_dir() or "_truncados" in d.parts:
            continue
        try:
            recente = max((f.stat().st_mtime for f in d.iterdir()), default=0)
        except OSError:
            continue
        if agora - recente < idade_min_h * 3600:
            continue
        if not any(d.glob("[0-9][0-9][0-9]*.pdf")):
            continue
        if arquivo is not None and not (arquivo / d.name[len("integra_"):] / "manifest.json").exists():
            continue
        res.append(d)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--arquivo", type=Path, default=ARQUIVO, help="raiz do sei_arquivo exigido (ver --sem-exigir-arquivo)")
    ap.add_argument("--sem-exigir-arquivo", action="store_true")
    ap.add_argument("--idade-min-h", type=float, default=3.0)
    ap.add_argument("--sem-recomprimir", action="store_true")
    ap.add_argument("--pastas", nargs="*", help="só estas pastas integra_* (ignora idade e arquivo)")
    ap.add_argument("--aplicar", action="store_true")
    a = ap.parse_args(argv)
    if a.pastas:
        alvos = [a.cache / p for p in a.pastas if (a.cache / p).is_dir()]
    else:
        alvos = pastas_elegiveis(a.cache, a.idade_min_h, None if a.sem_exigir_arquivo else a.arquivo)
    tot = {"pastas": 0, "nativos": 0, "imagem": 0, "ilegiveis": 0, "bytes_liberados": 0}
    for d in alvos:
        r = depurar_pasta(d, a.aplicar, not a.sem_recomprimir)
        tot["pastas"] += 1
        for k in ("nativos", "imagem", "ilegiveis", "bytes_liberados"):
            tot[k] += r.get(k, 0)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    tot["gb_liberados"] = round(tot.pop("bytes_liberados") / 1e9, 2)
    tot["ensaio"] = not a.aplicar
    print(json.dumps(tot, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
