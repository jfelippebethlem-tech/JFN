# -*- coding: utf-8 -*-
"""Testes TARGETED do helper de OCR de documentos do SEI (sem rede/browser/DuckDB)."""
from __future__ import annotations

import shutil

import pytest

from compliance_agent.sei.ocr_docs import eh_escaneado, ocr_documento


def _ocr_disponivel() -> bool:
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return False
    return shutil.which("tesseract") is not None


def _png_com_texto(texto: str, path):
    """Gera um PNG simples com `texto` em preto sobre branco (legível p/ OCR)."""
    pytest.importorskip("PIL")  # Pillow obrigatório para gerar a fixture
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (320, 120), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
    except Exception:
        font = ImageFont.load_default()
    draw.text((20, 20), texto, fill="black", font=font)
    img.save(path)
    return path


# --------------------------------------------------------------------------- #
# (b) eh_escaneado: heurística honesta
# --------------------------------------------------------------------------- #
def test_eh_escaneado_texto_vazio_eh_scan():
    assert eh_escaneado("", 1) is True
    assert eh_escaneado("   \n  ", 3) is True


def test_eh_escaneado_texto_rico_nao_eh_scan():
    rico = "Despacho de Encaminhamento. " * 50  # >> 40 chars/página
    assert eh_escaneado(rico, 1) is False
    assert eh_escaneado(rico, 2) is False


def test_eh_escaneado_protege_divisao_por_zero():
    # n_paginas inválido (0/None) não pode quebrar.
    assert eh_escaneado("", 0) is True
    assert eh_escaneado("", None) is True


# --------------------------------------------------------------------------- #
# (a) OCR de imagem sintética
# --------------------------------------------------------------------------- #
def test_ocr_imagem_sintetica(tmp_path):
    if not _ocr_disponivel():
        pytest.skip("pytesseract/tesseract indisponível — OCR não testável neste ambiente")
    png = _png_com_texto("SEI 2026", tmp_path / "fix.png")
    out = ocr_documento(png, lang="eng")  # número/palavra ASCII → 'eng' basta
    assert out, "OCR retornou vazio para imagem com texto claro"
    digitos = "".join(c for c in out if c.isdigit())
    assert "2026" in digitos or "SEI" in out.upper().replace(" ", "")


# --------------------------------------------------------------------------- #
# Degradação honesta: fonte inválida → "" (sem exceção)
# --------------------------------------------------------------------------- #
def test_fonte_inexistente_retorna_vazio():
    assert ocr_documento("/caminho/que/nao/existe_xyz.png") == ""


def test_tipo_de_fonte_invalido_retorna_vazio():
    assert ocr_documento(12345) == ""  # type: ignore[arg-type]
