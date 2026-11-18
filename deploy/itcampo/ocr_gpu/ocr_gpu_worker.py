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
MAX_PAG = int(os.environ.get("OCR_MAX_PAG", "120"))   # 200 dpi RGB ≈ 12 MB/página: 120 ≈ 1,4 GB no WSL
PAG_POR_CHAMADA = int(os.environ.get("OCR_PAG_CHAMADA", "48"))   # = --max-num-seqs do vLLM
VM1 = "vm1-ts:JFN/data/sei_cache/"
SINAL = BASE / "SESSAO_ATIVA"          # tocado pelo ocr_servico a cada página das sessões SEI


def ceder_as_sessoes(max_s: int = 600) -> None:
    """Captura ao vivo tem prioridade: enquanto uma sessão SEI pediu OCR há < 20 s, o lote espera (até 10 min)."""
    t0 = time.time()
    while SINAL.exists() and time.time() - SINAL.stat().st_mtime < 20 and time.time() - t0 < max_s:
        time.sleep(5)


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
    import surya_utf8  # acentos: o modelo gera ç/ã em Latin-1 (ver o módulo)
    surya_utf8.instalar()
    from surya import RecognitionPredictor, SuryaInferenceManager
    rec = RecognitionPredictor(SuryaInferenceManager())
    for d in (TMP, OUT):
        d.mkdir(parents=True, exist_ok=True)
    feitos = set(FEITOS.read_text().split()) if FEITOS.exists() else set()
    falhas = set(FALHAS.read_text().split()) if FALHAS.exists() else set()
    fila = [p for p in FILA.read_text().split() if p not in feitos and p not in falhas] if FILA.exists() else []
    log(ev="inicio", pendentes=len(fila), feitos=len(feitos))
    if any(OUT.rglob("*.ocr_gpu.txt")):     # sobra de lote interrompido: entrega antes de seguir
        r = subprocess.run(["rsync", "-a", "--ignore-existing", "--include=*/", "--include=*.ocr_gpu.txt",
                            "--include=*.ocr_gpu.json", "--exclude=*", str(OUT) + "/", VM1],
                           capture_output=True, text=True, timeout=1800)
        log(ev="sobra_entregue", rc=r.returncode)
    while True:
        if not fila:      # acabou: puxa a fila que a VM-1 remonta (tools/sei_ocr_gpu_fila.py); nada novo → 1 h
            r = subprocess.run(["rsync", "-a", "vm1-ts:JFN/data/sei_ocr_gpu_fila.txt", str(FILA)],
                               capture_output=True, text=True, timeout=300)
            fila = [p for p in FILA.read_text().split() if p not in feitos and p not in falhas] \
                if r.returncode == 0 and FILA.exists() else []
            log(ev="fila_da_vm1", rc=r.returncode, pendentes=len(fila))
            if not fila:
                time.sleep(3600)
                continue
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
        # Páginas de VÁRIOS PDFs na mesma chamada: com 1 PDF por vez (2–3 páginas) o vLLM rodava 2–6 sequências e
        # gerava ~100 tokens/s; o bench, com 79 páginas juntas, fazia 2,6 s/página (18/11/2026).
        pendentes = list(lote)
        while pendentes:
            ceder_as_sessoes()
            grupo, paginas = [], []                      # grupo = [(rel, doc_page_count, n)], paginas = [(rel, img)]
            while pendentes and len(paginas) < PAG_POR_CHAMADA:
                rel = pendentes.pop(0)
                pdf = TMP / rel
                try:
                    doc = fitz.open(pdf)
                    n = min(doc.page_count, MAX_PAG)
                    paginas += [(rel, Image.open(io.BytesIO(doc.load_page(i).get_pixmap(dpi=200).tobytes("png")))
                                 .convert("RGB")) for i in range(n)]
                    grupo.append((rel, doc.page_count, n))
                except (OSError, ValueError, RuntimeError, MemoryError) as e:   # PDF ruim não para o lote
                    log(ev="pdf_falhou", pdf=rel, erro=f"{type(e).__name__}: {str(e)[:200]}")
                    with FALHAS.open("a") as f:
                        f.write(rel + "\n")
                finally:
                    pdf.unlink(missing_ok=True)
            if not paginas:
                continue
            t0, textos = time.time(), []
            try:
                for k in range(0, len(paginas), PAG_POR_CHAMADA):
                    for res in rec([img for _, img in paginas[k:k + PAG_POR_CHAMADA]]):
                        textos.append("\n".join(_txt(b.html) for b in
                                                sorted(res.blocks, key=lambda b: b.reading_order or 0)))
            except (OSError, ValueError, RuntimeError) as e:    # falha da chamada: o grupo volta à fila desta rodada
                log(ev="grupo_falhou", pdfs=len(grupo), erro=f"{type(e).__name__}: {str(e)[:200]}")
                fila = [rel for rel, _, _ in grupo] + fila
                time.sleep(60)
                continue
            seg = round(time.time() - t0, 1)
            pos = 0
            for rel, total_pdf, n in grupo:
                partes, pos = textos[pos:pos + n], pos + n
                texto = "\n\n".join(f"[página {i + 1}]\n{t}" for i, t in enumerate(partes))
                destino = OUT / rel[:-4]
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.with_suffix(".ocr_gpu.txt").write_text(texto, encoding="utf-8")
                destino.with_suffix(".ocr_gpu.json").write_text(json.dumps(
                    {"motor": "surya-ocr-2.5 (vLLM, RTX 5070, it-campo)", "paginas": n, "paginas_pdf": total_pdf,
                     "cortado": total_pdf > n, "s_grupo": seg, "chars": len(texto),
                     "em": time.strftime("%F %T")}, ensure_ascii=False))
                pags_lote += n
                feitos.add(rel)
                with FEITOS.open("a") as f:
                    f.write(rel + "\n")
        # entrega à VM-1 — só o que não existe lá
        r = subprocess.run(["rsync", "-a", "--ignore-existing", "--include=*/", "--include=*.ocr_gpu.txt",
                            "--include=*.ocr_gpu.json", "--exclude=*", str(OUT) + "/", VM1],
                           capture_output=True, text=True, timeout=1800)
        if r.returncode == 0:
            shutil.rmtree(OUT); OUT.mkdir()
        dt = time.time() - t_lote
        log(ev="lote", pdfs=len(lote), paginas=pags_lote, s=round(dt), s_por_pag=round(dt / max(pags_lote, 1), 2),
            entregue=r.returncode == 0, restantes=len(fila))
    return 0


if __name__ == "__main__":
    sys.exit(main())
