"""OCR por IA na GPU do it-campo (Surya 2.5 via vLLM local) dos PDFs escaneados do arquivo frio do SEI.

Medido em 18/11/2026 com gabarito (79 páginas nativas 'sujadas' como escaneado): Surya acerta 99,7% dos valores em
R$ (Tesseract, o OCR de produção: 78,0%), 100% das datas (89,8%), 95,7% dos CNPJ (92,5%), 1,24 s/página.

Fila: ocr_fila.txt (caminhos integra_X/NNN.pdf no vm2-ts:~/arquivo_frio/sei_cache). Por lote: baixa da VM-2,
renderiza a 200 dpi, OCR, grava out/integra_X/NNN.ocr.txt (+ .ocr.json com motor/páginas/tempo) e ENTREGA à VM-1
(rsync --ignore-existing: nunca sobrescreve texto que já exista lá). Retoma de onde parou (feitos.txt).
Cede memória às sessões SEI: abaixo de 3 GB livres no WSL, espera.
"""
from __future__ import annotations

import html as _html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import fitz
from PIL import Image

BASE = Path.home() / "jfn-gpu" / "ocr"
FILA, FEITOS, FALHAS = BASE / "ocr_fila.txt", BASE / "feitos.txt", BASE / "falhas.txt"
TMP, OUT = BASE / "tmp", BASE / "out"
LOTE = int(os.environ.get("OCR_LOTE", "40"))
MAX_PAG = int(os.environ.get("OCR_MAX_PAG", "300"))
PAG_POR_CHAMADA = 8
VM1 = "vm1-ts:JFN/data/sei_cache/"


def log(**kw):
    with (BASE / "ocr_gpu.log").open("a") as f:
        f.write(json.dumps({"t": time.strftime("%F %T"), **kw}, ensure_ascii=False) + "\n")
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def mem_livre_gb() -> float:
    for ln in open("/proc/meminfo"):
        if ln.startswith("MemAvailable:"):
            return int(ln.split()[1]) / 1e6
    return 99.0


def _txt(h: str) -> str:
    h = re.sub(r"<(br|/p|/tr|/li|/h\d|/div)[^>]*>", "\n", h or "")
    h = re.sub(r"</t[dh]>", " | ", h)
    return _html.unescape(re.sub(r"<[^>]+>", "", h))


def main() -> int:
    from surya import RecognitionPredictor, SuryaInferenceManager
    rec = RecognitionPredictor(SuryaInferenceManager())
    for d in (TMP, OUT):
        d.mkdir(parents=True, exist_ok=True)
    feitos = set(FEITOS.read_text().split()) if FEITOS.exists() else set()
    falhas = set(FALHAS.read_text().split()) if FALHAS.exists() else set()
    fila = [p for p in FILA.read_text().split() if p not in feitos and p not in falhas]
    log(ev="inicio", pendentes=len(fila), feitos=len(feitos))
    while fila:
        if (BASE / "PAUSA").exists():
            time.sleep(60); continue
        if mem_livre_gb() < 3.0:
            log(ev="espera_memoria", livre_gb=round(mem_livre_gb(), 1)); time.sleep(120); continue
        lote, fila = fila[:LOTE], fila[LOTE:]
        lst = TMP / "lote.txt"
        lst.write_text("\n".join(lote) + "\n")
        r = subprocess.run(["rsync", "-a", "--files-from", str(lst), "vm2-ts:arquivo_frio/sei_cache/", str(TMP) + "/"],
                           capture_output=True, text=True, timeout=1800)
        if r.returncode not in (0, 23):
            log(ev="rsync_vm2_falhou", rc=r.returncode, erro=r.stderr[-300:]); fila = lote + fila; time.sleep(300); continue
        t_lote, pags_lote = time.time(), 0
        for rel in lote:
            pdf = TMP / rel
            try:
                doc = fitz.open(pdf)
                n = min(doc.page_count, MAX_PAG)
                imgs = [Image.open(io.BytesIO(doc.load_page(i).get_pixmap(dpi=200).tobytes("png"))).convert("RGB")
                        for i in range(n)]
                t0, partes = time.time(), []
                for k in range(0, n, PAG_POR_CHAMADA):
                    for res in rec(imgs[k:k + PAG_POR_CHAMADA]):
                        partes.append("\n".join(_txt(b.html) for b in
                                                sorted(res.blocks, key=lambda b: b.reading_order or 0)))
                texto = "\n\n".join(f"[página {i + 1}]\n{t}" for i, t in enumerate(partes))
                destino = OUT / rel[:-4]
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.with_suffix(".ocr_gpu.txt").write_text(texto, encoding="utf-8")
                destino.with_suffix(".ocr_gpu.json").write_text(json.dumps(
                    {"motor": "surya-ocr-2.5 (vLLM, RTX 5070, it-campo)", "paginas": n, "paginas_pdf": doc.page_count,
                     "cortado": doc.page_count > n, "s": round(time.time() - t0, 1), "chars": len(texto),
                     "em": time.strftime("%F %T")}, ensure_ascii=False))
                pags_lote += n
                feitos.add(rel)
                with FEITOS.open("a") as f:
                    f.write(rel + "\n")
            except Exception as e:  # noqa: BLE001 — um PDF ruim não para o lote; vai para falhas.txt
                log(ev="pdf_falhou", pdf=rel, erro=f"{type(e).__name__}: {str(e)[:200]}")
                with FALHAS.open("a") as f:
                    f.write(rel + "\n")
            finally:
                pdf.unlink(missing_ok=True)
        # entrega à VM-1 — só o que não existe lá
        r = subprocess.run(["rsync", "-a", "--ignore-existing", "--include=*/", "--include=*.ocr_gpu.txt",
                            "--include=*.ocr_gpu.json", "--exclude=*", str(OUT) + "/", VM1],
                           capture_output=True, text=True, timeout=1800)
        if r.returncode == 0:
            shutil.rmtree(OUT); OUT.mkdir()
        dt = time.time() - t_lote
        log(ev="lote", pdfs=len(lote), paginas=pags_lote, s=round(dt), s_por_pag=round(dt / max(pags_lote, 1), 2),
            entregue=r.returncode == 0, restantes=len(fila))
    log(ev="fim", feitos=len(feitos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
