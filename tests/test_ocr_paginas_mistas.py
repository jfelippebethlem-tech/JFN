# -*- coding: utf-8 -*-
"""Documento MISTO (páginas nativas + páginas escaneadas) não pode perder as escaneadas.

Defeito medido em 23/11/2026: a decisão de OCR era do DOCUMENTO inteiro — `ocr_documento` devolvia o texto nativo
quando a média passava de 40 caracteres por página, e `sei_arquivar` só chamava o OCR quando o documento inteiro
tinha menos de 200 caracteres. Um anexo com capa digitada e 9 páginas de nota fiscal escaneada saía só com a capa,
e ninguém via a falta (o documento "tem texto"). Conserto: com `completar_mistas=True` as páginas sem camada de
texto e com imagem grande vão ao OCR; o texto nativo das outras páginas fica INTACTO (regra
ocr-novo-nunca-substitui-texto: OCR só preenche o que estava vazio).
"""
from __future__ import annotations

import pytest

fitz = pytest.importorskip("fitz")

import compliance_agent.sei.ocr_docs as O  # noqa: E402

NATIVO = "Despacho de encaminhamento do processo ao setor financeiro para liquidação da despesa. " * 4


def _png_branco(w=600, h=800) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), 0)
    pix.set_rect(pix.irect, (255, 255, 255))
    return pix.tobytes("png")


def _pdf(paginas: list[str]) -> bytes:
    """'t' = página nativa com texto; 's' = página escaneada (imagem de página inteira, sem texto);
    'l' = página nativa com um logotipo pequeno."""
    doc = fitz.open()
    for tipo in paginas:
        pg = doc.new_page(width=595, height=842)
        if tipo in ("t", "l"):
            pg.insert_textbox(fitz.Rect(40, 40, 555, 800), NATIVO, fontsize=10)
        if tipo == "s":
            pg.insert_image(pg.rect, stream=_png_branco())
        if tipo == "l":
            pg.insert_image(fitz.Rect(40, 760, 100, 820), stream=_png_branco(60, 60))
    dados = doc.tobytes()
    doc.close()
    return dados


@pytest.fixture
def ocr_falso(monkeypatch):
    chamadas = []

    def _ocr(img, lang):
        chamadas.append(img.size)
        return f"NOTA FISCAL ESCANEADA {len(chamadas)} valor R$ 1.234,56"

    monkeypatch.setattr(O, "_ocr_pil", _ocr)
    monkeypatch.setattr(O, "_tesseract_ok", lambda: True)
    return chamadas


def test_misto_completa_so_as_paginas_escaneadas(ocr_falso):
    out = O.ocr_documento(_pdf(["t", "s", "s"]), tipo="pdf", completar_mistas=True)
    assert len(ocr_falso) == 2, "OCR só das 2 páginas escaneadas, nunca da nativa"
    assert "NOTA FISCAL ESCANEADA 1" in out and "NOTA FISCAL ESCANEADA 2" in out
    assert "Despacho de encaminhamento" in out


def test_misto_preserva_texto_nativo_intacto(ocr_falso):
    dados = _pdf(["t", "s"])
    nativo, _ = O._texto_nativo_pdf(dados)
    out = O.ocr_documento(dados, tipo="pdf", completar_mistas=True)
    assert nativo.strip() in out, "o texto nativo tem de sair inteiro, na ordem, sem troca"


def test_misto_mantem_ordem_das_paginas(ocr_falso):
    out = O.ocr_documento(_pdf(["s", "t", "s"]), tipo="pdf", completar_mistas=True)
    assert out.index("ESCANEADA 1") < out.index("Despacho") < out.index("ESCANEADA 2")


def test_sem_a_opcao_comportamento_antigo(ocr_falso):
    out = O.ocr_documento(_pdf(["t", "s"]), tipo="pdf")
    assert ocr_falso == [] and "ESCANEADA" not in out


def test_nativo_puro_nao_chama_ocr(ocr_falso):
    out = O.ocr_documento(_pdf(["t", "t", "l"]), tipo="pdf", completar_mistas=True)
    assert ocr_falso == [], "logotipo pequeno em página com texto não é página escaneada"
    assert "Despacho" in out


def test_interruptor_de_ambiente_desliga(ocr_falso, monkeypatch):
    monkeypatch.setenv("OCR_PAGINAS_MISTAS", "0")
    out = O.ocr_documento(_pdf(["t", "s"]), tipo="pdf", completar_mistas=True)
    assert ocr_falso == [] and "ESCANEADA" not in out


def test_orcamento_estourado_declara_paginas_que_faltaram(ocr_falso, monkeypatch):
    monkeypatch.setattr(O, "OCR_BUDGET_S", 0)
    out = O.ocr_documento(_pdf(["t", "s", "s", "s"]), tipo="pdf", completar_mistas=True)
    assert len(ocr_falso) == 1, "orçamento zero ainda faz a 1ª página"
    assert "OCR PARCIAL" in out and "1 de 3" in out


def test_paginas_escaneadas_lista_indices():
    assert O.paginas_escaneadas(_pdf(["t", "s", "l", "s"])) == [1, 3]
    assert O.paginas_escaneadas(_pdf(["t"])) == []


def test_arquivador_completa_documento_misto(tmp_path, ocr_falso):
    """Ponta a ponta no arquivador: anexo com página digitada + página escaneada sai com as duas."""
    from tools import sei_arquivar as A
    origem = tmp_path / "integra_270001_000001_2026"
    origem.mkdir()
    (origem / "000.pdf").write_bytes(_pdf(["t", "s"]))
    man = A.arquivar(origem, tmp_path / "arq", "270001/000001/2026")
    doc = man["docs"][0]
    corpo = (tmp_path / "arq" / doc["texto"]).read_text(encoding="utf-8")
    assert "Despacho de encaminhamento" in corpo and "NOTA FISCAL ESCANEADA 1" in corpo
    assert doc["ocr"] is True and doc.get("ocr_paginas") == "mistas"


def test_arquivador_documento_nativo_nao_chama_ocr(tmp_path, ocr_falso):
    """Controle negativo: anexo só digitado (com logotipo) não paga OCR nenhum."""
    from tools import sei_arquivar as A
    origem = tmp_path / "integra_270001_000002_2026"
    origem.mkdir()
    (origem / "000.pdf").write_bytes(_pdf(["t", "l"]))
    man = A.arquivar(origem, tmp_path / "arq", "270001/000002/2026")
    assert ocr_falso == [] and not man["docs"][0].get("ocr")


def test_cada_pagina_nativa_sai_identica(ocr_falso):
    """Prova real de 23/11 (doc de 239 páginas): a junção tem de ser a da extração nativa, página por página."""
    dados = _pdf(["s", "t", "s", "t", "t"])
    out = O.ocr_documento(dados, tipo="pdf", completar_mistas=True)
    with fitz.open(stream=dados, filetype="pdf") as doc:
        for pg in doc:
            assert pg.get_text().strip() in out
