#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR de TODAS as páginas-imagem de um processo de execução SEI (NFs escaneadas).
Extrai candidatos a Nota Fiscal de limpeza (MGS emitente + valor + competência) p/ a perícia.
Salva data/sei_cache/ocr_nfs_<proc>.json. VM-guarded. Uso: ocr_nfs_execucao.py <pdf>"""
import fitz
import pytesseract
import re
import json
import sys
import io
from pathlib import Path
from PIL import Image
sys.path.insert(0, "/home/ubuntu/JFN")
from tools.vm_guard import preflight, cleanup_orphans

PDF = sys.argv[1] if len(sys.argv) > 1 else "data/sei_cache/INTEGRA_330005_000018_2025.pdf"
OUT = Path("data/sei_cache/ocr_nfs_" + Path(PDF).stem + ".json")
VAL = re.compile(r'\b(\d{1,3}(?:\.\d{3})*,\d2)\b')
COMP = re.compile(r'(\d{2}/\d{4}|janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)', re.I)
NF = re.compile(r'(?:n[ºo°.]\s*|n[uú]mero\s*)(\d{2,9})', re.I)
LIMP = re.compile(r'(limpeza|conserva|higiene|asseio|copeira|portaria|recep[çc])', re.I)


def run():
    doc = fitz.open(PDF)
    achados = []
    for i in range(doc.page_count):
        pg = doc.load_page(i)
        t = pg.get_text()
        if len(t.strip()) > 200:   # já tem texto, não é imagem-NF
            continue
        if not pg.get_images():
            continue
        try:
            pix = pg.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            ocr = pytesseract.image_to_string(img, lang="por")
        except Exception as e:
            achados.append({"p": i + 1, "erro": str(e)[:60]}); continue
        is_mgs = "19.088.605" in ocr or "19088605" in ocr or "MGS CLEAN" in ocr.upper()
        is_nf = bool(re.search(r'NOTA FISCAL|NFS-?e|DANFE|presta[çc][ãa]o de servi', ocr, re.I))
        if is_mgs and (is_nf or LIMP.search(ocr)):
            vals = sorted(set(VAL.findall(ocr)), key=lambda v: -float(v.replace(".", "").replace(",", ".")))
            achados.append({"p": i + 1, "tipo": "NF_LIMPEZA_MGS",
                            "nf": NF.findall(ocr)[:3], "valores": vals[:6],
                            "competencia": list(dict.fromkeys(COMP.findall(ocr)))[:4],
                            "trecho": " ".join(ocr.split())[:300]})
            print(f"  p{i+1}: NF MGS-limpeza? vals={vals[:4]} comp={COMP.findall(ocr)[:3]}", flush=True)
    doc.close()
    OUT.write_text(json.dumps({"pdf": PDF, "n_nfs": len(achados), "nfs": achados}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f">>> {len(achados)} candidatos · salvo: {OUT}")


if __name__ == "__main__":
    ok, motivo = preflight()
    if not ok:
        print(json.dumps({"ok": False, "vm_guard": motivo})); sys.exit(1)
    cleanup_orphans()
    try:
        run()
    finally:
        cleanup_orphans()
