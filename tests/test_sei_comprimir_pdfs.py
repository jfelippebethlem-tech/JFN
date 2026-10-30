# -*- coding: utf-8 -*-
"""Encolher os PDFs do cache do SEI nunca pode perder página nem texto, e só troca quando ganha."""
from __future__ import annotations

import os
import shutil
import time

import pytest

fitz = pytest.importorskip("fitz")
from tools import sei_comprimir_pdfs as C  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("gs") is None, reason="Ghostscript ausente")


def _escaneado(p, paginas=2):
    """PDF com página 'escaneada' (imagem de 288 dpi numa página pequena) e uma linha de texto. O /ebook só
    reamostra acima de 225 dpi; página pequena mantém o teste rápido."""
    d = fitz.open()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 1000, 1000), False)
    pix.set_rect(pix.irect, (235, 235, 230))
    for y in range(0, 1000, 16):                       # textura para o JPEG não zerar o tamanho
        pix.set_rect(fitz.IRect(0, y, 1000, y + 8), (40 + y % 200, 60, 90))
    for i in range(paginas):
        pg = d.new_page(width=250, height=250)
        pg.insert_image(pg.rect, pixmap=pix)
        pg.insert_text((20, 30), f"NOTA FISCAL {i} - TEXTO", fontsize=10)
    d.save(str(p), deflate=False)
    d.close()


def test_escaneado_encolhe_sem_perder_pagina_nem_texto(tmp_path):
    p = tmp_path / "INTEGRA_330005_000018_2025.pdf"
    _escaneado(p)
    os.utime(p, (1_700_000_000, 1_700_000_000))
    antes = p.stat().st_size
    r = C.comprimir(p, aplicar=True)
    assert r.get("trocado"), r
    assert p.stat().st_size <= antes * C.FATOR_MAX
    d = fitz.open(str(p))
    assert d.page_count == 2 and "NOTA FISCAL 1" in d[1].get_text()
    d.close()
    assert p.stat().st_mtime == 1_700_000_000, "a idade é da captura, não da compressão"
    assert [x.name for x in tmp_path.iterdir()] == [p.name], "sobrou temporário"


def test_pdf_so_de_texto_nao_ganha_e_fica_intacto(tmp_path):
    p = tmp_path / "despacho.pdf"
    d = fitz.open()
    d.new_page().insert_text((72, 72), "Despacho sem imagem", fontsize=12)
    d.save(str(p), deflate=True, garbage=4)
    d.close()
    original = p.read_bytes()
    r = C.comprimir(p, aplicar=True)
    assert not r.get("trocado") and r.get("mantido")
    assert p.read_bytes() == original


def test_ensaio_nao_grava(tmp_path):
    p = tmp_path / "a.pdf"
    _escaneado(p, paginas=1)
    original = p.read_bytes()
    r = C.comprimir(p, aplicar=False)
    assert r.get("trocaria")
    assert p.read_bytes() == original


def test_candidatos_pulam_truncados_e_captura_recente(tmp_path):
    velho = time.time() - 10 * 86400
    (tmp_path / "_truncados").mkdir()
    for nome in ("velho.pdf", "_truncados/t.pdf", "novo.pdf", "pequeno.pdf"):
        (tmp_path / nome).write_bytes(b"%PDF" + b"0" * (10 if nome == "pequeno.pdf" else 2_000_000))
    for nome in ("velho.pdf", "_truncados/t.pdf", "pequeno.pdf"):
        os.utime(tmp_path / nome, (velho, velho))
    assert [p.name for p in C.candidatos(tmp_path)] == ["velho.pdf"]
