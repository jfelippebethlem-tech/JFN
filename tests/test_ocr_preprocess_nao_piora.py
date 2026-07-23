"""O pré-processamento do OCR não pode PIORAR o resultado.

Achado em 2026-07-23 numa Nota Fiscal escaneada (2480×3508, processo
260007/019524/2024 doc 4): a imagem original rendia 2.272 caracteres no
tesseract; depois do `_preprocess_para_ocr` (threshold adaptativo 31/10)
rendia ZERO. O passo que existe para melhorar o OCR o destruía em silêncio —
e o documento saía do arquivo como "sem teor", sendo uma NF (pela doutrina da
casa, é a NF que fecha a análise de duplicidade).
"""
import pytest

from compliance_agent.sei import ocr_docs


class _ImgFalsa:
    """Marcador: o teste só precisa distinguir 'original' de 'pré-processada'."""

    def __init__(self, nome):
        self.nome = nome


def test_usa_original_quando_preprocess_zera(monkeypatch):
    original = _ImgFalsa("original")
    monkeypatch.setattr(ocr_docs, "_preprocess_para_ocr",
                        lambda img: _ImgFalsa("preprocessada"))

    class _PT:
        TesseractError = RuntimeError

        @staticmethod
        def image_to_string(alvo, lang=None):
            return "" if alvo.nome == "preprocessada" else "TEOR DA NOTA FISCAL " * 8

    monkeypatch.setitem(__import__("sys").modules, "pytesseract", _PT)

    saida = ocr_docs._ocr_pil(original, "por")
    assert "NOTA FISCAL" in saida, "com pré-processamento vazio, vale a imagem original"


def test_mantem_preprocessada_quando_ela_e_melhor(monkeypatch):
    original = _ImgFalsa("original")
    monkeypatch.setattr(ocr_docs, "_preprocess_para_ocr",
                        lambda img: _ImgFalsa("preprocessada"))

    class _PT:
        TesseractError = RuntimeError

        @staticmethod
        def image_to_string(alvo, lang=None):
            return "TEXTO LIMPO E LONGO DO SCAN " * 8 if alvo.nome == "preprocessada" else "ruido"

    monkeypatch.setitem(__import__("sys").modules, "pytesseract", _PT)

    saida = ocr_docs._ocr_pil(original, "por")
    assert "TEXTO LIMPO" in saida, "o pré-processamento continua valendo quando ajuda"


def test_nota_fiscal_real_volta_a_ter_teor():
    """Regressão sobre o documento real que expôs o bug (pulado se o PDF sumir)."""
    from pathlib import Path
    pdf = Path("data/sei_cache/integra_260007_019524_2024/004.pdf")
    if not pdf.exists() or not ocr_docs._tesseract_ok():
        pytest.skip("PDF de referência ou tesseract indisponível")
    texto = ocr_docs.ocr_documento(pdf.read_bytes(), tipo="pdf")
    assert len(texto.strip()) > 500, "a NF escaneada tem de render teor de verdade"
