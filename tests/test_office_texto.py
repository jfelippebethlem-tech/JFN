"""Extrair texto de anexos Office (Excel/Word) do SEI.

Achado 2026-07-23: anexos em formato Office (planilha de medição/faturamento EXCEL,
minuta Word) faziam `_conteudo_via_arvore` cair em `tipo=None → continue` → doc
perdido. São AUDIT-CRÍTICOS (a planilha tem os números da medição). Tooling presente:
openpyxl (.xlsx), xlrd (.xls), python-docx (.docx). Só o .doc binário antigo fica de
fora (precisa antiword/libreoffice, não instalados).
"""
import io

from compliance_agent.sei.office_texto import texto_de_office


def _xlsx_bytes(linhas):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for ln in linhas:
        ws.append(ln)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _docx_bytes(paragrafos):
    import docx
    d = docx.Document()
    for p in paragrafos:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_extrai_planilha_xlsx():
    body = _xlsx_bytes([["Item", "Valor"],
                        ["Aluguel container", "12.500,00"],
                        ["3a Medição", "TOTAL 250.000,00"]])
    txt = texto_de_office(body)
    assert "Aluguel container" in txt
    assert "250.000,00" in txt
    assert "Medição" in txt


def test_extrai_word_docx():
    body = _docx_bytes(["MINUTA DE RESOLUÇÃO SES",
                        "Art. 1º Fica aprovada a contratação.",
                        "Valor global: R$ 1.200.000,00"])
    txt = texto_de_office(body)
    assert "MINUTA DE RESOLUÇÃO" in txt
    assert "1.200.000,00" in txt


def test_doc_binario_antigo_devolve_vazio_sem_quebrar():
    """.doc OLE2 antigo (sem antiword): devolve '' honesto, não explode."""
    ole2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 200
    assert texto_de_office(ole2) == ""


def test_bytes_lixo_devolve_vazio():
    assert texto_de_office(b"nao e office nenhum") == ""
    assert texto_de_office(b"") == ""


def test_pdf_nao_e_tratado_aqui():
    """PDF não é Office — devolve '' (o caminho de PDF/OCR cuida dele)."""
    assert texto_de_office(b"%PDF-1.7 ...") == ""


def _tem_soffice():
    import shutil
    return shutil.which("soffice") is not None


def _doc_antigo_bytes(paragrafos):
    """Cria um .doc BINÁRIO antigo convertendo um .docx via libreoffice (o único jeito
    de gerar .doc em teste — não há lib Python que escreva .doc)."""
    import subprocess
    import tempfile
    import os
    from pathlib import Path
    docx = _docx_bytes(paragrafos)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "x.docx"
        src.write_bytes(docx)
        subprocess.run(["soffice", "--headless",
                        f"-env:UserInstallation=file://{td}/prof",
                        "--convert-to", "doc", "--outdir", td, str(src)],
                       capture_output=True, timeout=120)
        doc = Path(td) / "x.doc"
        return doc.read_bytes() if doc.exists() else b""


def test_doc_binario_antigo_extrai_com_libreoffice():
    import pytest
    if not _tem_soffice():
        pytest.skip("soffice (libreoffice) não instalado")
    body = _doc_antigo_bytes(["MINUTA DE RESOLUCAO ANTIGA",
                              "Art. 1 Fica aprovada a contratacao pelo valor de 500 mil."])
    assert body[:4] == b"\xd0\xcf\x11\xe0", "fixture deveria ser .doc OLE2"
    from compliance_agent.sei.office_texto import texto_de_office
    txt = texto_de_office(body)
    assert "MINUTA DE RESOLUCAO" in txt
    assert "500 mil" in txt


def _docx_com_xml_quebrado() -> bytes:
    """docx cujo document.xml tem elemento inválido — o lxml do python-docx levanta XMLSyntaxError."""
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
                   'officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
                   '2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", '<?xml version="1.0"?>\n<w:document xmlns:w="x"><w:body><w:p><1x/>'
                                        '</w:p></w:body></w:document>')
    return buf.getvalue()


def test_xml_quebrado_nao_derruba_a_captura():
    """21/11/2026: `lxml.etree.XMLSyntaxError: StartTag: invalid element name` saiu do `texto_de_office` e derrubou a
    captura inteira (rc=1) — 37 vezes em 3 dias, 330001/001026/2024 19 vezes sem nunca capturar. A promessa é
    'nunca levanta': anexo ilegível dá '' e o documento fica como não capturado, o resto do processo segue."""
    assert texto_de_office(_docx_com_xml_quebrado(), "application/vnd.openxmlformats-officedocument."
                                                       "wordprocessingml.document") == ""
