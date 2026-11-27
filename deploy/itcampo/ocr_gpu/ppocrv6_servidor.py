"""Servidor local do PP-OCRv6 na GPU do it-campo (27/11/2026) — o motor principal do E5 escolhido pela bancada O3.6/O3.7
no controle nativo (verdade = texto do PDF, 200 páginas): PP-OCRv6 97,07% de acerto · RapidOCR 94,67% · Surya 69,42%;
na GPU (RTX 5070, paddlepaddle-gpu cu129) 1,19 s/página (p50) contra 4,4 s do Surya, MESMO acerto da CPU.

Roda no ambiente isolado ~/ocr-ppocrv6 (paddle com CUDA), fora do worker do JFN — o executor do E5
(`aplicacao/estagios/ocr.ExecutorPPOCRv6`) é só o cliente, como o do Surya é do vLLM. Montagem do texto = a da bancada
(`tools.sei_ocr_reserva._linhas` + `corrigir`), para o motor de produção ser exatamente o medido.

  GET  /saude          → {"motor": "...", "pronto": true}
  POST /ler  (PNG)     → {"texto", "linhas": [{"texto","bbox","conf"}], "largura", "altura", "motor"}
Escuta só em 127.0.0.1. Um pedido por vez (a placa é uma só). Uso: PYTHONPATH=~/JFN-worker python ppocrv6_servidor.py
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version

import numpy as np

PORTA = int(os.environ.get("JFN_PPOCRV6_PORTA", "8792"))
DPI = int(os.environ.get("JFN_OCR_DPI", "200"))
_trava = threading.Lock()


def _motor_nome() -> str:
    return f"ppocrv6@paddleocr{version('paddleocr')} medium det+rec (GPU it-campo, paddle {version('paddlepaddle-gpu')}) dpi{DPI}"


def montar(eng):
    from tools import sei_ocr_reserva as R

    def ler(img) -> dict:
        itens, linhas = [], []
        for res in eng.predict(img):
            scores = list(res.get("rec_scores") or [])
            for k, (b, t) in enumerate(zip(res["rec_polys"], res["rec_texts"])):
                b = np.asarray(b)
                itens.append(((b[:, 1].min() + b[:, 1].max()) / 2, b[:, 0].min(), b[:, 1].max() - b[:, 1].min(), t))
                linhas.append({"texto": t, "bbox": [round(float(b[:, 0].min()), 1), round(float(b[:, 1].min()), 1),
                                                    round(float(b[:, 0].max()), 1), round(float(b[:, 1].max()), 1)],
                               "conf": round(float(scores[k]), 4) if k < len(scores) else None})
        return {"texto": R.corrigir(R._linhas(itens)), "linhas": linhas}
    return ler


def main() -> None:
    from paddleocr import PaddleOCR
    from PIL import Image
    import io
    eng = PaddleOCR(text_detection_model_name="PP-OCRv6_medium_det", text_recognition_model_name="PP-OCRv6_medium_rec",
                    use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
                    device="gpu:0")
    ler = montar(eng)
    nome = _motor_nome()

    class H(BaseHTTPRequestHandler):
        def _json(self, cod: int, obj: dict) -> None:
            corpo = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(cod); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo))); self.end_headers(); self.wfile.write(corpo)

        def do_GET(self):
            self._json(200, {"motor": nome, "pronto": True}) if self.path == "/saude" else self._json(404, {})

        def do_POST(self):
            if self.path != "/ler":
                return self._json(404, {})
            n = int(self.headers.get("Content-Length") or 0)
            try:
                img = np.asarray(Image.open(io.BytesIO(self.rfile.read(n))).convert("RGB"))
                with _trava:
                    out = ler(img)
                self._json(200, {**out, "largura": int(img.shape[1]), "altura": int(img.shape[0]), "motor": nome})
            except (OSError, ValueError, RuntimeError) as e:          # imagem ilegível / falha do motor: o cliente vê
                self._json(500, {"erro": f"{type(e).__name__}: {str(e)[:300]}"})

        def log_message(self, *a):                                    # sem log por pedido
            pass

    ThreadingHTTPServer(("127.0.0.1", PORTA), H).serve_forever()


if __name__ == "__main__":
    main()
