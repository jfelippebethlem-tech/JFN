"""OCR por IA na GPU do it-campo (18/11/2026): com JFN_OCR_GPU_URL a página vai à GPU; falhou → Tesseract."""
from __future__ import annotations

import io

from PIL import Image

from compliance_agent.sei import ocr_docs as O


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _img():
    return Image.new("RGB", (40, 20), "white")


def test_com_url_usa_a_gpu_e_nao_chama_tesseract(monkeypatch):
    monkeypatch.setenv("JFN_OCR_GPU_URL", "http://127.0.0.1:8791/ocr")
    chamadas = []
    monkeypatch.setattr(O.urllib.request, "urlopen",
                        lambda req, timeout=0: chamadas.append(req.full_url) or _Resp(("NOTA FISCAL Nº 53 R$ 94.999,98 " * 3).encode()))
    monkeypatch.setattr(O, "_ocr_tesseract", lambda img, lang: (_ for _ in ()).throw(AssertionError("não devia")))
    assert "94.999,98" in O._ocr_pil(_img(), "por") and chamadas == ["http://127.0.0.1:8791/ocr"]


def test_gpu_fora_do_ar_cai_no_tesseract(monkeypatch):
    monkeypatch.setenv("JFN_OCR_GPU_URL", "http://127.0.0.1:8791/ocr")

    def _falha(req, timeout=0):
        raise OSError("connection refused")
    monkeypatch.setattr(O.urllib.request, "urlopen", _falha)
    monkeypatch.setattr(O, "_ocr_tesseract", lambda img, lang: "texto do tesseract")
    assert O._ocr_pil(_img(), "por") == "texto do tesseract"


def test_sem_url_nem_tenta_a_gpu(monkeypatch):
    monkeypatch.delenv("JFN_OCR_GPU_URL", raising=False)
    monkeypatch.setattr(O.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não devia")))
    monkeypatch.setattr(O, "_ocr_tesseract", lambda img, lang: "tess")
    assert O._ocr_pil(_img(), "por") == "tess"
