# -*- coding: utf-8 -*-
"""O coletor do DOERJ lê o PDF da edição — o DOM do visualizador pdf.js só tem o sumário."""
from __future__ import annotations

import fitz

from compliance_agent.collectors.doerj import _texto_pdf


def _pdf(paginas: list[str]) -> bytes:
    doc = fitz.open()
    for t in paginas:
        pg = doc.new_page()
        pg.insert_text((72, 72), t)
    return doc.tobytes()


def test_texto_pdf_le_todas_as_paginas():
    t = _texto_pdf(_pdf(["PORTARIA N 1 abre sindicancia", "DECRETO N 2 nomeia fulano"]))
    assert "sindicancia" in t and "nomeia fulano" in t
    assert t.index("sindicancia") < t.index("nomeia")


def test_pdf_invalido_devolve_vazio_sem_estourar():
    assert _texto_pdf(b"isto nao e um pdf") == ""
