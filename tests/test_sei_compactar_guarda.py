"""A guarda do compactador de cache SEI tem de REJEITAR de verdade.

Um deletador cuja verificação é no-op apaga o que não devia. Cada garantia é
testada isoladamente: sem PDF integral, sem texto, ou captura em curso → não apaga.
"""
import json

import tools.sei_compactar_cache as C


def _pdf(caminho, paginas=1):
    import fitz
    d = fitz.open()
    for i in range(paginas):
        d.new_page().insert_text((60, 60), f"pagina {i}")
    d.save(str(caminho))
    d.close()


def _monta(tmp_path, monkeypatch, *, integral=True, texto=True, completo=True,
           docs_no_arquivo=True, pgs_peca=3, pgs_integral=4):
    cache, arq = tmp_path / "cache", tmp_path / "arq"
    tag = "080001_007110_2023"
    (cache / f"integra_{tag}").mkdir(parents=True)
    _pdf(cache / f"integra_{tag}" / "000.pdf", pgs_peca)
    if integral:
        _pdf(cache / f"INTEGRA_{tag}.pdf", pgs_integral)
    (cache / f"integra_{tag}" / "manifest.json").write_text(
        json.dumps({"completo": completo, "docs": [{"i": 0}]}), encoding="utf-8")
    (arq / tag / "texto").mkdir(parents=True)
    if texto:
        (arq / tag / "texto" / "000_contrato.txt").write_text("teor", encoding="utf-8")
    (arq / tag / "manifest.json").write_text(json.dumps(
        {"docs": [{"i": 0}] if docs_no_arquivo else []}), encoding="utf-8")
    monkeypatch.setattr(C, "CACHE", cache)
    monkeypatch.setattr(C, "ARQUIVO", arq)
    return tag


def test_apaga_quando_as_tres_garantias_valem(tmp_path, monkeypatch):
    tag = _monta(tmp_path, monkeypatch)
    ok, motivo = C._seguro(tag)
    assert ok, motivo


def test_recusa_sem_pdf_integral(tmp_path, monkeypatch):
    tag = _monta(tmp_path, monkeypatch, integral=False)
    ok, motivo = C._seguro(tag)
    assert not ok and "integral" in motivo


def test_recusa_sem_texto_extraido(tmp_path, monkeypatch):
    tag = _monta(tmp_path, monkeypatch, texto=False)
    ok, motivo = C._seguro(tag)
    assert not ok and "texto" in motivo


def test_recusa_captura_em_curso(tmp_path, monkeypatch):
    """Retomada usa as peças soltas: apagar no meio do download perde trabalho."""
    tag = _monta(tmp_path, monkeypatch, completo=False)
    ok, motivo = C._seguro(tag)
    assert not ok and ("curso" in motivo or "parcial" in motivo)


def test_recusa_arquivo_sem_documentos(tmp_path, monkeypatch):
    tag = _monta(tmp_path, monkeypatch, docs_no_arquivo=False)
    ok, motivo = C._seguro(tag)
    assert not ok and "documento" in motivo


def _pecas(tmp_path, tag):
    return sorted((tmp_path / "cache" / f"integra_{tag}").glob("[0-9][0-9][0-9]*.pdf"))


def test_recusa_integral_desatualizado(tmp_path, monkeypatch):
    """Integral com MENOS páginas que as peças = remontagem pendente: apagar perderia documento."""
    tag = _monta(tmp_path, monkeypatch, pgs_peca=10, pgs_integral=4)
    ok, motivo = C._seguro(tag, _pecas(tmp_path, tag))
    assert not ok and "DESATUALIZADO" in motivo


def test_aceita_quando_integral_cobre_as_paginas(tmp_path, monkeypatch):
    tag = _monta(tmp_path, monkeypatch, pgs_peca=3, pgs_integral=4)
    ok, motivo = C._seguro(tag, _pecas(tmp_path, tag))
    assert ok, motivo


def test_recusa_peca_ilegivel(tmp_path, monkeypatch):
    """PDF corrompido não é contabilizável — não se aposta no que não se consegue ler."""
    tag = _monta(tmp_path, monkeypatch)
    (tmp_path / "cache" / f"integra_{tag}" / "001.pdf").write_bytes(b"lixo nao-pdf")
    ok, motivo = C._seguro(tag, _pecas(tmp_path, tag))
    assert not ok and "ilegível" in motivo
