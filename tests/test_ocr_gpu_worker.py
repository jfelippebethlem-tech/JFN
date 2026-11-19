"""Trabalhador do OCR por IA (it-campo): página nativa não vai à GPU e o fluxo contínuo devolve o texto na ordem."""
import importlib.util
import sys
import threading
import types
from pathlib import Path

import fitz
import pytest
from PIL import Image

_spec = importlib.util.spec_from_file_location(
    "ocr_gpu_worker", Path(__file__).resolve().parent.parent / "deploy/itcampo/ocr_gpu/ocr_gpu_worker.py")
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)

TEXTO = "Nota fiscal 001234567 CNPJ 12.345.678/0001-90 valor R$ 1.234,56 " * 5   # > 200 caracteres


def _pdf(caminho: Path, paginas: list[str]) -> Path:
    """'nativa' = texto vetorial; 'escaneada' = imagem de página inteira; 'curta' = pouco texto, sem imagem."""
    doc = fitz.open()
    for tipo in paginas:
        pg = doc.new_page(width=595, height=842)
        if tipo == "nativa":
            pg.insert_textbox(fitz.Rect(40, 40, 555, 800), TEXTO, fontsize=9)
        elif tipo == "escaneada":
            img = Image.new("RGB", (400, 560), "white")
            import io
            b = io.BytesIO(); img.save(b, "PNG")
            pg.insert_image(pg.rect, stream=b.getvalue())
        elif tipo == "curta":
            pg.insert_text((40, 60), "Anexo I")
    doc.save(caminho)
    return caminho


@pytest.fixture(autouse=True)
def _base_temporaria(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "BASE", tmp_path)                 # o log do trabalhador vai para a pasta do teste
    monkeypatch.setattr(W, "SINAL", tmp_path / "SESSAO_ATIVA")


class RecFalso:
    """Imita o RecognitionPredictor: uma resposta por imagem, com o tamanho da imagem no texto."""

    def __init__(self, falhar_em: int | None = None):
        self.imagens, self.trava, self.falhar_em = 0, threading.Lock(), falhar_em

    def __call__(self, imgs):
        with self.trava:
            self.imagens += len(imgs)
            n = self.imagens
        if self.falhar_em is not None and n == self.falhar_em:
            raise RuntimeError("vLLM caiu")
        return [types.SimpleNamespace(blocks=[types.SimpleNamespace(html=f"<p>ocr {im.size[0]}</p>", reading_order=0)])
                for im in imgs]


def test_pagina_nativa_so_com_texto_visivel_e_sem_imagem_grande(tmp_path):
    d = fitz.open(_pdf(tmp_path / "a.pdf", ["nativa", "escaneada", "curta"]))
    assert W.pagina_nativa(d.load_page(0)) is True
    assert W.pagina_nativa(d.load_page(1)) is False      # imagem de página inteira = escaneada
    assert W.pagina_nativa(d.load_page(2)) is False      # pouco texto: vai ao OCR (pode ser texto desenhado)


def test_pagina_com_texto_invisivel_de_ocr_antigo_vai_para_a_gpu(tmp_path):
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_textbox(fitz.Rect(40, 40, 555, 800), TEXTO, fontsize=9, render_mode=3)   # camada de OCR invisível
    doc.save(tmp_path / "inv.pdf")
    assert W.pagina_nativa(fitz.open(tmp_path / "inv.pdf").load_page(0)) is False


def test_ler_lote_nativa_nao_vai_a_gpu_e_ordem_das_paginas_e_mantida(tmp_path):
    a = _pdf(tmp_path / "a.pdf", ["escaneada", "nativa", "escaneada"])
    b = _pdf(tmp_path / "b.pdf", ["nativa", "nativa"])
    c = _pdf(tmp_path / "c.pdf", ["escaneada"] * 5)
    rec = RecFalso()
    res, ruins, refazer = W.ler_lote([("x/a.pdf", a), ("x/b.pdf", b), ("x/c.pdf", c)], rec, em_voo=3)
    assert ruins == [] and refazer == []
    assert rec.imagens == 7                                   # 2 de a + 5 de c; as 3 nativas não foram à GPU
    assert res["x/a.pdf"]["nativas"] == [1] and res["x/b.pdf"]["nativas"] == [0, 1]
    assert res["x/a.pdf"]["textos"][0].startswith("ocr ") and "Nota fiscal 001234567" in res["x/a.pdf"]["textos"][1]
    assert res["x/c.pdf"]["paginas"] == 5 and len(res["x/c.pdf"]["textos"]) == 5


def test_pdf_ilegivel_vai_para_ruins_e_falha_da_gpu_devolve_so_aquele_pdf(tmp_path):
    (tmp_path / "ruim.pdf").write_bytes(b"isto nao e pdf")
    a = _pdf(tmp_path / "a.pdf", ["escaneada"])
    b = _pdf(tmp_path / "b.pdf", ["escaneada", "escaneada"])
    rec = RecFalso(falhar_em=2)                               # a 2ª página enviada falha
    res, ruins, refazer = W.ler_lote([("r.pdf", tmp_path / "ruim.pdf"), ("a.pdf", a), ("b.pdf", b)], rec, em_voo=1)
    assert ruins == ["r.pdf"]
    assert refazer == ["b.pdf"] and list(res) == ["a.pdf"]   # o PDF com página falhada volta à fila inteiro


def test_corte_de_paginas_respeita_max_pag(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "MAX_PAG", 2)
    a = _pdf(tmp_path / "a.pdf", ["escaneada"] * 4)
    res, _, _ = W.ler_lote([("a.pdf", a)], RecFalso(), em_voo=2)
    assert res["a.pdf"]["paginas"] == 2 and res["a.pdf"]["paginas_pdf"] == 4
