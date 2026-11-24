"""Bancada SOTA 23/11/2026 — mesmas 177 imagens PNG 200 dpi de ~/jfn-gpu/bench_digitos (as 40 da bancada saem de
paginas.json na medição). Grava textos_<motor>.json e tempos_<motor>.json AO LADO; nada existente é alterado.
    python bench_sota.py ppocrv6 [threads]          # PP-OCRv6 medium det+rec, CPU (paddle), linhas + correção decimal
    python bench_sota.py paddlevl <url_vllm>        # pipeline PaddleOCR-VL-1.6 (layout em CPU, VL no vLLM da GPU)
    python bench_sota.py ovis <url_vllm>            # OvisOCR2 servido pelo vLLM (temperature 0)
Só as páginas de paginas.json (ou todas com --todas). Tempo por página, pico de RSS do processo; VRAM medida à parte.
"""
import base64
import json
import os
import resource
import sys
import time
from pathlib import Path

BASE = Path.home() / "jfn-gpu" / "bench_digitos"
OUT = Path.home() / "jfn-gpu" / "bench_sota"
motor = sys.argv[1]
ks = json.loads((OUT / "paginas.json").read_text())
img = {k: BASE / "img" / (k.replace("/", "_") + ".png") for k in ks}
out_t, out_s = OUT / f"textos_{motor}.json", OUT / f"tempos_{motor}.json"
textos = json.loads(out_t.read_text()) if out_t.exists() else {}
tempos = json.loads(out_s.read_text()) if out_s.exists() else {}


def rss_mb():
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)


if motor == "ppocrv6":
    sys.path.insert(0, str(Path.home() / "jfn-gpu" / "ocr-cpu"))
    import numpy as np
    import sei_ocr_reserva as R                       # _linhas e corrigir: o MESMO pós-processo da reserva (RapidOCR)
    from paddleocr import PaddleOCR
    th = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    eng = PaddleOCR(text_detection_model_name="PP-OCRv6_medium_det", text_recognition_model_name="PP-OCRv6_medium_rec",
                    use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
                    device="cpu", cpu_threads=th)

    def ler(k):
        it = []
        for r in eng.predict(str(img[k])):
            for b, t in zip(r["rec_polys"], r["rec_texts"]):
                b = np.asarray(b)
                it.append(((b[:, 1].min() + b[:, 1].max()) / 2, b[:, 0].min(), b[:, 1].max() - b[:, 1].min(), t))
        return R.corrigir(R._linhas(it))
elif motor == "paddlevl":
    from paddleocr import PaddleOCRVL
    eng = PaddleOCRVL(pipeline_version="v1.6", vl_rec_backend="vllm-server", vl_rec_server_url=sys.argv[2],
                      vl_rec_api_model_name="PaddleOCR-VL-1.6-0.9B", device="cpu")

    def ler(k):
        return "\n\n".join(r.markdown["markdown_texts"] if hasattr(r, "markdown") else str(r)
                           for r in eng.predict(str(img[k])))
elif motor == "ovis":
    import urllib.request
    url = sys.argv[2].rstrip("/") + "/chat/completions"
    modelo = os.environ.get("OVIS_MODELO", "ATH-MaaS/OvisOCR2")

    def ler(k):
        b64 = base64.b64encode(img[k].read_bytes()).decode()
        corpo = {"model": modelo, "temperature": 0, "max_tokens": 6000,
                 "messages": [{"role": "user", "content": [
                     {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                     {"type": "text", "text": os.environ.get("OVIS_PROMPT", "Convert the document to markdown.")}]}]}
        rq = urllib.request.Request(url, json.dumps(corpo).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(rq, timeout=900) as f:
            return json.loads(f.read())["choices"][0]["message"]["content"]
elif motor == "deepdoc":
    # DeepDoc do RAGFlow, isolado: módulo Python da v0.27.3 (a v1.0 reescreveu o DeepDoc em Go com pdfium/onnxruntime
    # via cgo) + shim de `common`/`rag` (só caminho do modelo e PARALLEL_DEVICES=0); modelos InfiniFlow/deepdoc (ONNX).
    # Texto = OCR em linhas + correção decimal (o mesmo pós-processo da reserva); layout e tabela (TSR) registrados.
    DD = Path.home() / "jfn-gpu" / "bench_sota" / "deepdoc"
    sys.path[:0] = [str(DD / "shim"), str(DD / "rf027"), str(Path.home() / "jfn-gpu" / "ocr-cpu")]
    import numpy as np
    from PIL import Image
    import sei_ocr_reserva as R
    from deepdoc.vision import OCR, LayoutRecognizer, Recognizer, TableStructureRecognizer
    eng, lay, tsr = OCR(), LayoutRecognizer("layout"), TableStructureRecognizer()
    estrutura = {}

    def ler(k):
        im = Image.open(img[k]).convert("RGB")
        arr = np.asarray(im)
        it = []
        for box, (t, sc) in eng(arr) or []:
            b = np.asarray(box)
            it.append(((b[:, 1].min() + b[:, 1].max()) / 2, b[:, 0].min(), b[:, 1].max() - b[:, 1].min(), t))
        # detector de layout cru (o Recognizer base): [{"type", "score", "bbox": [x0, y0, x1, y1]}] por página
        regioes = Recognizer.__call__(lay, [arr], 0.2, 16)[0]
        tipos = [r.get("type") for r in regioes]
        tabelas = [r for r in regioes if r.get("type") == "table"]
        celulas = 0
        for r in tabelas:
            x0, y0, x1, y1 = (int(v) for v in r["bbox"])
            try:                                   # TSR: [[{label, bbox, score}, ...]] por recorte
                res = tsr([im.crop((x0, y0, x1, y1))])
                celulas += len(res[0]) if res and isinstance(res[0], list) else 0
            except (ValueError, TypeError, IndexError) as exc:
                print(f"[bench_sota] TSR falhou no recorte {k}: {exc!r} — células não contadas", file=sys.stderr)
        estrutura[k] = {"regioes": len(tipos), "tipos": sorted(set(t for t in tipos if t)), "tabelas": len(tabelas),
                        "elementos_tsr": celulas}
        (OUT / "estrutura_deepdoc.json").write_text(json.dumps(estrutura, ensure_ascii=False))
        return R.corrigir(R._linhas(it))
else:
    raise SystemExit(f"motor desconhecido: {motor}")

for k in ks:
    if k in textos:
        continue
    t0 = time.time()
    try:
        textos[k] = ler(k)
        erro = ""
    except (RuntimeError, ValueError, OSError, TypeError, KeyError, IndexError, MemoryError) as e:  # bancada: a página que falha fica registrada, não para
        erro = f"{type(e).__name__}: {str(e)[:300]}"
    tempos[k] = {"s": round(time.time() - t0, 2), "pico_rss_mb": rss_mb(), "erro": erro}
    out_t.write_text(json.dumps(textos, ensure_ascii=False))
    out_s.write_text(json.dumps(tempos, ensure_ascii=False))
    print(k, tempos[k]["s"], "s", len(textos.get(k, "")), "chars", erro, flush=True)
