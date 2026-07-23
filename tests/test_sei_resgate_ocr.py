"""O resgate por OCR só toca documento SÓ-IMAGEM, e não estraga o que já tem texto."""
import json

import pytest

import tools.sei_resgatar_escaneados as R


def _pdf_texto(caminho, texto="TERMO DE REFERENCIA objeto do contrato"):
    import fitz
    d = fitz.open()
    d.new_page().insert_text((60, 60), texto)
    d.save(str(caminho))
    d.close()


def _pdf_imagem(caminho):
    """PDF com imagem e sem texto — o escaneado típico."""
    import fitz
    d = fitz.open()
    pg = d.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 60))
    pix.clear_with(200)
    pg.insert_image(fitz.Rect(20, 20, 200, 200), pixmap=pix)
    d.save(str(caminho))
    d.close()


def _pdf_branco(caminho):
    import fitz
    d = fitz.open()
    d.new_page()
    d.save(str(caminho))
    d.close()


def test_reconhece_so_imagem(tmp_path):
    _pdf_imagem(tmp_path / "img.pdf")
    _pdf_texto(tmp_path / "txt.pdf")
    _pdf_branco(tmp_path / "branco.pdf")
    assert R._so_imagem(tmp_path / "img.pdf") is True
    assert R._so_imagem(tmp_path / "txt.pdf") is False, "documento com texto não é escaneado"
    assert R._so_imagem(tmp_path / "branco.pdf") is False, "PDF em branco não tem o que resgatar"


def test_nao_toca_documento_que_ja_tem_texto(tmp_path, monkeypatch):
    tag = "080001_007110_2023"
    (tmp_path / "cache" / f"integra_{tag}").mkdir(parents=True)
    _pdf_imagem(tmp_path / "cache" / f"integra_{tag}" / "000.pdf")
    (tmp_path / "arq" / tag / "texto").mkdir(parents=True)
    (tmp_path / "arq" / tag / "manifest.json").write_text(json.dumps({"docs": [
        {"i": 0, "titulo": "Contrato", "chars": 5000, "texto": "texto/000_c.txt"}]}),
        encoding="utf-8")
    monkeypatch.setattr(R, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(R, "ARQUIVO", tmp_path / "arq")

    assert R.resgatar(tag, aplicar=True) == [], "doc com 5000 chars não entra no resgate"


def test_ensaio_nao_grava(tmp_path, monkeypatch):
    tag = "080001_007110_2023"
    (tmp_path / "cache" / f"integra_{tag}").mkdir(parents=True)
    _pdf_imagem(tmp_path / "cache" / f"integra_{tag}" / "000.pdf")
    (tmp_path / "arq" / tag / "texto").mkdir(parents=True)
    man = tmp_path / "arq" / tag / "manifest.json"
    original = json.dumps({"docs": [{"i": 0, "titulo": "Anexo", "chars": 0,
                                     "texto": "texto/000_a.txt"}]})
    man.write_text(original, encoding="utf-8")
    monkeypatch.setattr(R, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(R, "ARQUIVO", tmp_path / "arq")
    monkeypatch.setattr("compliance_agent.sei.ocr_docs.ocr_documento",
                        lambda *a, **k: "TEOR RECUPERADO POR OCR " * 5)

    R.resgatar(tag, aplicar=False)

    assert man.read_text(encoding="utf-8") == original, "ensaio não pode gravar"


def test_aplicar_grava_teor_e_marca_ocr(tmp_path, monkeypatch):
    tag = "080001_007110_2023"
    (tmp_path / "cache" / f"integra_{tag}").mkdir(parents=True)
    _pdf_imagem(tmp_path / "cache" / f"integra_{tag}" / "000.pdf")
    (tmp_path / "arq" / tag / "texto").mkdir(parents=True)
    man = tmp_path / "arq" / tag / "manifest.json"
    man.write_text(json.dumps({"docs": [{"i": 0, "titulo": "Anexo medição", "fase": "execucao",
                                         "tipo": "anexo", "chars": 0,
                                         "texto": "texto/000_a.txt"}]}), encoding="utf-8")
    monkeypatch.setattr(R, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(R, "ARQUIVO", tmp_path / "arq")
    monkeypatch.setattr("compliance_agent.sei.ocr_docs.ocr_documento",
                        lambda *a, **k: "MEDICAO 03 valor executado 250.000,00 " * 3)

    ganhos = R.resgatar(tag, aplicar=True)

    assert len(ganhos) == 1
    novo = json.loads(man.read_text(encoding="utf-8"))
    assert novo["docs"][0]["ocr"] is True
    assert novo["docs"][0]["chars"] > 60
    corpo = (tmp_path / "arq" / tag / "texto" / "000_a.txt").read_text(encoding="utf-8")
    assert "MEDICAO 03" in corpo and "[OCR]" in corpo
