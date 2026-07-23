"""Documento escaneado preserva o PDF ORIGINAL (imagens = fotos de prova).

Ao remover o GET-direto envenenador (c3c6831), o fluxo passou a gravar SÓ texto —
o que perderia as imagens de documentos de medição/relatório fotográfico/fiscalização
(_TIPOS_FOTO em sei_arquivar), que o arquivador salva como fotos de prova de execução.

_gravar_doc preserva o PDF original quando há bytes de anexo escaneado (imagens
intactas → arquivador salva as fotos), e usa texto só para documento nativo (editor,
sem imagens a preservar). Assim o fix do envenenamento não regride a captura de fotos.
"""
import fitz

from compliance_agent.sei.pdf_texto import gravar_doc as _gravar_doc


def _pdf_com_imagem_bytes() -> bytes:
    d = fitz.open()
    pg = d.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 80))
    pix.clear_with(180)
    pg.insert_image(fitz.Rect(20, 20, 300, 300), pixmap=pix)
    b = d.tobytes()
    d.close()
    return b


def test_escaneado_preserva_pdf_original_com_imagem(tmp_path):
    fp = tmp_path / "005.pdf"
    anexo = _pdf_com_imagem_bytes()

    ok = _gravar_doc(fp, "Relatório Fotográfico de Medição", "texto ocr do laudo", anexo)

    assert ok
    d = fitz.open(str(fp))
    tem_imagem = any(pg.get_images() for pg in d)
    d.close()
    assert tem_imagem, "o PDF original com imagem tem de ser preservado (fotos de prova)"


def test_nativo_grava_texto(tmp_path):
    fp = tmp_path / "000.pdf"
    ok = _gravar_doc(fp, "Despacho", "Encaminho os autos para parecer.\n" * 5, None)
    assert ok
    d = fitz.open(str(fp))
    assert "Encaminho os autos" in "\n".join(p.get_text() for p in d)
    d.close()


def test_anexo_nao_pdf_cai_para_texto(tmp_path):
    """Bytes que não são PDF (ex.: imagem solta) não viram um .pdf quebrado — usa o texto."""
    fp = tmp_path / "007.pdf"
    ok = _gravar_doc(fp, "Anexo", "teor extraido por ocr do documento", b"\x89PNG\r\n")
    assert ok
    d = fitz.open(str(fp))
    assert "teor extraido" in "\n".join(p.get_text() for p in d)
    d.close()


def test_texto_vazio_nao_grava(tmp_path):
    fp = tmp_path / "009.pdf"
    assert _gravar_doc(fp, "Vazio", "", None) is False
    assert not fp.exists()
