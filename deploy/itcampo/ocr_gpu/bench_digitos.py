"""Bench de DÍGITO TROCADO por motor de OCR (Surya × Tesseract × RapidOCR) com gabarito automático — 18/11/2026.

Gabarito = texto NATIVO do próprio PDF (é a verdade). Dois conjuntos:
  · reais    — páginas nativas que estavam NA FILA da GPU (bench_vazao/pdfs: imagem < 10% da página, ≥ 200 caracteres),
               rasterizadas limpas a 200 dpi como o trabalhador faz;
  · sujas    — as 60 PDFs nativas do bench antigo (~/jfn-gpu/bench/pdfs, 2 páginas cada), 'sujadas' como escaneado
               (mesma função e seed 7 do bench_ocr.py).

A métrica que importa para fiscalização não é só o recall: é o número ERRADO emitido com cara de certo.
  recall     = números do gabarito que o motor leu exatos
  emitido_errado = números que o motor escreveu e não existem na página (por 100 emitidos)
  trocado    = errado que difere de um número verdadeiro AUSENTE da leitura em 1–2 dígitos, mesmo tamanho (troca de dígito)
Validação cruzada (A∩B): o número só vale se os dois motores leram igual; divergiu → INDISPONÍVEL.

    python bench_digitos.py gabarito                 # (venv do Surya) grava PNGs + gabarito.json
    python bench_digitos.py ler surya|tesseract      # (venv do Surya)
    python bench_digitos.py ler rapidocr             # (venv ocr-cpu: importa o motor de ~/jfn-gpu/ocr-cpu/sei_ocr_reserva.py)
    python bench_digitos.py medir                    # tabela por motor e por par
"""
from __future__ import annotations

import io
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

BASE = Path.home() / "jfn-gpu" / "bench_digitos"
RX = {"valor": re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3})*,\d{2}(?![\d,])"),
      "cnpj": re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)"),
      "data": re.compile(r"(?<!\d)\d{2}/\d{2}/\d{4}(?!\d)"),
      "numero": re.compile(r"(?<![\d.,/])\d{6,}(?![\d,/])")}     # NF, empenho, OB, protocolo: sequência ≥ 6 dígitos


def _dig(s: str) -> str:
    return re.sub(r"\D", "", s)


def numeros(t: str) -> dict[str, set[str]]:
    t = re.sub(r"\s+", " ", t or "")
    out = {k: {m for m in rx.findall(t)} for k, rx in RX.items()}
    out["cnpj"] = {_dig(m) for m in out["cnpj"] if len(_dig(m)) == 14}
    return out


def eh_troca(e: str, faltantes: set[str]) -> bool:
    de = _dig(e)
    for t in faltantes:
        dt = _dig(t)
        if len(dt) == len(de) and 1 <= sum(a != b for a, b in zip(dt, de)) <= 2:
            return True
    return False


def pagina_nativa(pg) -> bool:
    """Texto visível ≥ 200 caracteres, nada invisível (camada de OCR) e imagens < 10% da página."""
    area = abs(pg.rect) or 1.0
    cobertura = sum(abs(r & pg.rect) for x in pg.get_images() for r in pg.get_image_rects(x[0])) / area
    invisivel = any(s.get("type") == 3 for s in pg.get_texttrace())
    return cobertura < 0.10 and not invisivel and len(pg.get_text().strip()) >= 200


def gabarito() -> None:
    import fitz
    import numpy as np
    from PIL import Image, ImageFilter
    random.seed(7); np.random.seed(7)

    def sujar(img):                                       # = bench_ocr.py
        g = img.convert("L").rotate(random.uniform(-1.2, 1.2), expand=True, fillcolor=255)
        g = g.filter(ImageFilter.GaussianBlur(0.8))
        a = np.asarray(g).astype(np.float32) + np.random.normal(0, 12, (g.height, g.width))
        g = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        b = io.BytesIO(); g.save(b, "JPEG", quality=45); return Image.open(io.BytesIO(b.getvalue())).convert("RGB")

    (BASE / "img").mkdir(parents=True, exist_ok=True)
    gab = {}
    for p in sorted((Path.home() / "jfn-gpu" / "bench_vazao" / "pdfs").glob("*.pdf")):
        with fitz.open(p) as d:
            for i in range(min(d.page_count, 30)):
                pg = d.load_page(i)
                if pagina_nativa(pg):
                    k = f"real/{p.stem}#{i}"
                    pg.get_pixmap(dpi=200).save(BASE / "img" / (k.replace("/", "_") + ".png"))
                    gab[k] = pg.get_text()
    for p in sorted((Path.home() / "jfn-gpu" / "bench" / "pdfs").glob("*.pdf")):
        try:
            d = fitz.open(p)
        except (OSError, ValueError, RuntimeError):
            continue
        for i in range(min(2, d.page_count)):
            v = d.load_page(i).get_text()
            if len(re.sub(r"\s+", " ", v).strip()) < 300:
                continue
            img = Image.open(io.BytesIO(d.load_page(i).get_pixmap(dpi=200).tobytes("png"))).convert("RGB")
            k = f"suja/{p.stem}#{i}"
            sujar(img).save(BASE / "img" / (k.replace("/", "_") + ".png"))
            gab[k] = v
    (BASE / "gabarito.json").write_text(json.dumps(gab, ensure_ascii=False), encoding="utf-8")
    print({"real": sum(k.startswith("real") for k in gab), "suja": sum(k.startswith("suja") for k in gab)})


def ler(motor: str) -> None:
    from PIL import Image
    gab = json.loads((BASE / "gabarito.json").read_text(encoding="utf-8"))
    imgs = {k: BASE / "img" / (k.replace("/", "_") + ".png") for k in gab}
    t0, textos = time.time(), {}
    if motor == "surya":
        import html as _html
        sys.path.insert(0, str(Path.home() / "jfn-gpu"))
        import surya_utf8
        surya_utf8.instalar()
        from surya import RecognitionPredictor, SuryaInferenceManager
        rec = RecognitionPredictor(SuryaInferenceManager())

        def _txt(h):
            h = re.sub(r"<(br|/p|/tr|/li|/h\d|/div)[^>]*>", "\n", h or "")
            h = re.sub(r"</t[dh]>", " | ", h)
            return _html.unescape(re.sub(r"<[^>]+>", "", h))
        ks = list(imgs)
        for j in range(0, len(ks), 48):
            for k, r in zip(ks[j:j + 48], rec([Image.open(imgs[k]).convert("RGB") for k in ks[j:j + 48]])):
                textos[k] = "\n".join(_txt(b.html) for b in sorted(r.blocks, key=lambda b: b.reading_order or 0))
    elif motor == "tesseract":                            # binário de produção, por, 1 fio (OMP_THREAD_LIMIT=1 nas sessões)
        for k, f in imgs.items():
            textos[k] = subprocess.run(["tesseract", str(f), "stdout", "-l", "por"], capture_output=True,
                                       env={**os.environ, "OMP_THREAD_LIMIT": "1"}).stdout.decode("utf-8", "replace")
    elif motor == "rapidocr":
        import numpy as np
        sys.path.insert(0, str(Path.home() / "jfn-gpu" / "ocr-cpu"))
        import sei_ocr_reserva as R
        eng = R.motor_ocr()
        for k, f in imgs.items():
            r = eng(np.ascontiguousarray(np.asarray(Image.open(f).convert("RGB"))))
            it = []
            for b, t in zip(r.boxes if r.boxes is not None else [], r.txts or []):
                b = np.asarray(b)
                it.append(((b[:, 1].min() + b[:, 1].max()) / 2, b[:, 0].min(), b[:, 1].max() - b[:, 1].min(), t))
            textos[k] = R.corrigir(R._linhas(it))
    else:
        raise SystemExit(f"motor desconhecido: {motor}")
    (BASE / f"textos_{motor}.json").write_text(json.dumps(textos, ensure_ascii=False), encoding="utf-8")
    print(motor, len(textos), "páginas", round((time.time() - t0) / max(len(textos), 1), 2), "s/página")


def medir() -> dict:
    gab = json.loads((BASE / "gabarito.json").read_text(encoding="utf-8"))
    motores = {m: json.loads((BASE / f"textos_{m}.json").read_text(encoding="utf-8"))
               for m in ("surya", "tesseract", "rapidocr") if (BASE / f"textos_{m}.json").exists()}
    combos = list(motores) + [f"{a}∩{b}" for i, a in enumerate(motores) for b in list(motores)[i + 1:]]
    out = {}
    for conj in ("real", "suja"):
        ks = [k for k in gab if k.startswith(conj) and all(k in t for t in motores.values())]
        for c in combos:
            s = {cl: [0, 0, 0, 0] for cl in RX}            # verdadeiros, acertos, emitidos, trocados
            for k in ks:
                v = numeros(gab[k])
                partes = [numeros(motores[m][k]) for m in c.split("∩")]
                for cl in RX:
                    e = set.intersection(*[p[cl] for p in partes])
                    falt = v[cl] - e
                    errados = e - v[cl]
                    s[cl][0] += len(v[cl]); s[cl][1] += len(v[cl] & e); s[cl][2] += len(e)
                    s[cl][3] += sum(eh_troca(x, falt) for x in errados)
            tot = [sum(x[i] for x in s.values()) for i in range(4)]
            out[f"{conj}/{c}"] = {"paginas": len(ks), "n_numeros": tot[0],
                                  "recall_%": round(100 * tot[1] / max(tot[0], 1), 1),
                                  "emitido_errado_%": round(100 * (tot[2] - tot[1]) / max(tot[2], 1), 2),
                                  "trocado_por_100_verdadeiros": round(100 * tot[3] / max(tot[0], 1), 2),
                                  "trocados": tot[3],
                                  **{f"{cl}_recall_%": round(100 * x[1] / max(x[0], 1), 1) for cl, x in s.items()},
                                  **{f"{cl}_trocados": x[3] for cl, x in s.items()},
                                  **{f"n_{cl}": x[0] for cl, x in s.items()}}
            print(f"{conj}/{c}", json.dumps(out[f'{conj}/{c}'], ensure_ascii=False), flush=True)
    (BASE / "resultado.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"gabarito": gabarito, "medir": medir}.get(cmd, lambda: ler(sys.argv[2]))()
