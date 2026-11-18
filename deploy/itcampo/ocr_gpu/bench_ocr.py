"""Bench OCR com GABARITO: PDFs nativos (texto embutido = verdade) renderizados como imagem, limpos e
'escaneados' (cinza, rotação leve, desfoque, ruído, JPEG). Motores: Tesseract por (o da produção, 200 dpi)
x Surya (GPU). Métricas: CER, recall de CNPJ / valor R$ / data, s/página."""
import io
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path
import fitz
import numpy as np
from PIL import Image, ImageFilter
from rapidfuzz.distance import Levenshtein

PDFS = sorted(Path(sys.argv[1]).glob("*.pdf"))
MAXPAG = 2
random.seed(7); np.random.seed(7)

ACENTO = re.compile(r"\b\w*[áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ]\w*\b")
RX = {"cnpj": re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}"),
      "valor": re.compile(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b"),
      "data": re.compile(r"\b\d{2}/\d{2}/\d{2,4}\b")}

def norm(t): return re.sub(r"\s+", " ", t).strip()
def dig(s): return re.sub(r"\D", "", s)

def campos(t):
    t2 = norm(t)
    return {"cnpj": {dig(m) for m in RX["cnpj"].findall(t2) if len(dig(m)) == 14},
            "valor": set(RX["valor"].findall(t2)), "data": set(RX["data"].findall(t2)),
            "acentuada": set(ACENTO.findall(t2))}

def sujar(img):
    g = img.convert("L").rotate(random.uniform(-1.2, 1.2), expand=True, fillcolor=255)
    g = g.filter(ImageFilter.GaussianBlur(0.8))
    a = np.asarray(g).astype(np.float32) + np.random.normal(0, 12, (g.height, g.width))
    g = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    b = io.BytesIO(); g.save(b, "JPEG", quality=45); return Image.open(io.BytesIO(b.getvalue())).convert("RGB")

amostras = []
for p in PDFS:
    try: doc = fitz.open(p)
    except (OSError, ValueError, RuntimeError): continue
    for i in range(min(MAXPAG, doc.page_count)):
        verdade = doc.load_page(i).get_text()
        if len(norm(verdade)) < 300: continue
        img = Image.open(io.BytesIO(doc.load_page(i).get_pixmap(dpi=int(os.environ.get("DPI", "200"))).tobytes("png"))).convert("RGB")
        amostras.append((f"{p.name}#{i}", verdade, img))
print("páginas com gabarito:", len(amostras), flush=True)

def tess(img):
    b = io.BytesIO(); img.save(b, "PNG")
    return subprocess.run(["tesseract", "stdin", "stdout", "-l", "por"], input=b.getvalue(), capture_output=True).stdout.decode("utf-8", "ignore")

import html as _html
import surya_utf8  # acentos: o modelo gera ç/ã em Latin-1 (ver o módulo)
surya_utf8.instalar()
from surya import RecognitionPredictor, SuryaInferenceManager
rec = RecognitionPredictor(SuryaInferenceManager())
def _txt(h):
    h = re.sub(r"<(br|/p|/tr|/li|/h\d|/div)[^>]*>", "\n", h or "")
    h = re.sub(r"</t[dh]>", " ", h)
    return _html.unescape(re.sub(r"<[^>]+>", "", h))
def surya_lote(imgs):
    res = rec(imgs)
    return ["\n".join(_txt(b.html) for b in sorted(r.blocks, key=lambda b: b.reading_order or 0)) for r in res]

out = {}
for cond in ("limpa", "escaneada"):
    imgs = [a[2] if cond == "limpa" else sujar(a[2]) for a in amostras]
    for motor in [m for m in ("tesseract", "surya") if m not in os.environ.get("PULAR", "").split(",")]:
        t0 = time.time()
        textos = [tess(im) for im in imgs] if motor == "tesseract" else surya_lote(imgs)
        dt = (time.time() - t0) / len(imgs)
        cer = []; rec_ = {k: [0, 0] for k in (*RX, "acentuada")}
        for (nome, verdade, _), t in zip(amostras, textos):
            v, o = norm(verdade), norm(t)
            cer.append(Levenshtein.normalized_distance(v, o))
            cv, co = campos(verdade), campos(t)
            for k in (*RX, "acentuada"):
                rec_[k][0] += len(cv[k] & co[k]); rec_[k][1] += len(cv[k])
        out[f"{cond}/{motor}"] = {"CER_mediana_%": round(100 * float(np.median(cer)), 1),
                                 **{f"acerto_{k}_%": round(100 * a / max(b, 1), 1) for k, (a, b) in rec_.items()},
                                 **{f"n_{k}": b for k, (a, b) in rec_.items()}, "s_por_pagina": round(dt, 2)}
        print(cond, motor, json.dumps(out[f"{cond}/{motor}"], ensure_ascii=False), flush=True)
json.dump(out, open(os.environ.get("SAIDA", "bench_ocr.json"), "w"), ensure_ascii=False, indent=1)
