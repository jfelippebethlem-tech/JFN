"""Serviço local de OCR por IA (Surya 2.5 via vLLM) para as sessões de captura SEI do it-campo.

POST /ocr  (corpo = imagem PNG/JPEG de UMA página)  →  200 text/plain com o texto (tabelas em linhas "a | b").
GET  /saude → 200 "ok". Escuta só em 127.0.0.1:8791. As sessões chamam via `JFN_OCR_GPU_URL`
(compliance_agent/sei/ocr_docs._ocr_gpu); sem o serviço, elas voltam ao Tesseract sozinhas.
"""
from __future__ import annotations

import html as _html
import io
import re
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image
import surya_utf8  # acentos: o modelo gera ç/ã em Latin-1 (ver o módulo)
surya_utf8.instalar()
from surya import RecognitionPredictor, SuryaInferenceManager

_REC = RecognitionPredictor(SuryaInferenceManager())
_TRAVA = threading.Semaphore(4)          # no máximo 4 páginas em voo (o vLLM enfileira o resto)
SINAL = Path.home() / "jfn-gpu" / "ocr" / "SESSAO_ATIVA"   # o lote em massa cede a GPU enquanto este arquivo é recente
MAX_BYTES = 30 * 1024 * 1024


def _txt(h: str) -> str:
    h = re.sub(r"<(br|/p|/tr|/li|/h\d|/div)[^>]*>", "\n", h or "")
    h = re.sub(r"</t[dh]>", " | ", h)
    return _html.unescape(re.sub(r"<[^>]+>", "", h))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):          # sem log de conteúdo
        pass

    def _resp(self, cod: int, corpo: str):
        b = corpo.encode("utf-8")
        self.send_response(cod)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._resp(200 if self.path == "/saude" else 404, "ok" if self.path == "/saude" else "")

    def do_POST(self):
        if self.path != "/ocr":
            return self._resp(404, "")
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 < n <= MAX_BYTES:
            return self._resp(413, "")
        try:
            SINAL.parent.mkdir(parents=True, exist_ok=True)
            SINAL.touch()
            img = Image.open(io.BytesIO(self.rfile.read(n))).convert("RGB")
            with _TRAVA:
                r = _REC([img])[0]
            self._resp(200, "\n".join(_txt(b.html) for b in sorted(r.blocks, key=lambda b: b.reading_order or 0)))
        except (OSError, ValueError, RuntimeError) as e:   # erro vira 500; a sessão cai para o Tesseract
            self._resp(500, type(e).__name__)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8791), H).serve_forever()
