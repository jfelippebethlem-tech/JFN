# -*- coding: utf-8 -*-
"""Teste TARGETED de compliance_agent.forense.pdf_metadados (digitais de PDF — proxy do sinal de IP do ADELE/TCU).

Estratégia (leve, VM 2 vCPU): PDFs mínimos gerados com fitz (PyMuPDF, já no venv) com metadados CONTROLADOS
em tmp_path; a lógica de agrupamento também é coberta lib-independente via monkeypatch de `metadados_pdf`.
Cobre: extração; agrupamento producer+author; guard anti-FP de producer genérico; criação no mesmo minuto;
degradação HONESTA (libs ausentes → None + warning INDISPONÍVEL; PDF corrompido → None + warning).
Rodar só este arquivo:  .venv/bin/python -m pytest tests/forense/test_pdf_metadados.py -q
"""
from __future__ import annotations

import logging

import pytest

import compliance_agent.forense.pdf_metadados as pm
from compliance_agent.forense import mesma_origem, metadados_pdf

fitz = pytest.importorskip("fitz", reason="PyMuPDF ausente — testes com PDF real pulados")


def _pdf(caminho, **meta) -> str:
    """PDF de 1 página com metadados controlados (chaves fitz: author/producer/creator/creationDate/modDate)."""
    doc = fitz.open()
    doc.new_page()
    doc.set_metadata(meta)
    doc.save(str(caminho))
    doc.close()
    return str(caminho)


# ═══════════════════════════════ metadados_pdf ═══════════════════════════════
def test_metadados_pdf_extrai_campos(tmp_path):
    p = _pdf(tmp_path / "a.pdf", author="Escritorio Silva Contabil", producer="GeradorPropostas v2",
             creator="Sistema X", creationDate="D:20260701101530", modDate="D:20260702090000")
    m = metadados_pdf(p)
    assert m is not None
    assert set(m) == {"author", "producer", "creator", "creation", "moddate"}
    assert m["author"] == "Escritorio Silva Contabil"
    assert m["producer"] == "GeradorPropostas v2"
    assert "202607011015" in m["creation"].replace("-", "").replace(":", "")


def test_metadados_pdf_corrompido_retorna_none_com_warning(tmp_path, caplog):
    ruim = tmp_path / "ruim.pdf"
    ruim.write_bytes(b"isto nao e um pdf de verdade")
    with caplog.at_level(logging.WARNING, logger="compliance_agent.forense.pdf_metadados"):
        assert metadados_pdf(str(ruim)) is None
    assert any("falhou" in r.message or "NÃO extraídos" in r.message for r in caplog.records)


def test_metadados_pdf_sem_nenhuma_lib_e_indisponivel_explicito(tmp_path, monkeypatch, caplog):
    """Lição OCR no-op: sem lib de PDF o retorno é None E o warning INDISPONÍVEL aparece (nunca silencioso)."""
    p = _pdf(tmp_path / "a.pdf", author="X", producer="Y")
    monkeypatch.setattr(pm, "_importar", lambda nome: None)
    with caplog.at_level(logging.WARNING, logger="compliance_agent.forense.pdf_metadados"):
        assert pm.metadados_pdf(p) is None
    assert any("INDISPONÍVEL" in r.message for r in caplog.records)


# ═══════════════════════════════ mesma_origem (PDFs reais) ═══════════════════════════════
def test_mesma_origem_agrupa_producer_author(tmp_path):
    """2 'concorrentes' com mesmo producer+author não-genéricos agrupam; o 3º (distinto) fica fora."""
    a = _pdf(tmp_path / "a.pdf", author="Maria Contadora", producer="GeradorPropostas v2",
             creationDate="D:20260701101000")
    b = _pdf(tmp_path / "b.pdf", author="Maria Contadora", producer="GeradorPropostas v2",
             creationDate="D:20260702154500")
    _pdf(tmp_path / "c.pdf", author="Outra Pessoa", producer="OutroGerador",
         creationDate="D:20260703120000")
    grupos = mesma_origem([a, b, str(tmp_path / "c.pdf")])
    pa = [g for g in grupos if g["campo_comum"] == "producer+author"]
    assert len(pa) == 1
    assert sorted(pa[0]["grupo"]) == sorted([a, b])
    assert "maria contadora" in pa[0]["valor"]


def test_guard_producer_generico_sem_author_nao_agrupa(tmp_path):
    """iText/wkhtmltopdf etc. sozinhos (author vazio) são universais — NÃO agrupam (guard anti-FP)."""
    a = _pdf(tmp_path / "a.pdf", author="", producer="iText 7.1.4", creationDate="D:20260701101000")
    b = _pdf(tmp_path / "b.pdf", author="", producer="iText 7.1.4", creationDate="D:20260702154500")
    assert mesma_origem([a, b]) == []


def test_producer_generico_com_author_igual_agrupa(tmp_path):
    """Producer genérico + MESMO author não-vazio → agrupa (o author sustenta a coincidência)."""
    a = _pdf(tmp_path / "a.pdf", author="Joao Despachante", producer="wkhtmltopdf 0.12",
             creationDate="D:20260701101000")
    b = _pdf(tmp_path / "b.pdf", author="Joao Despachante", producer="wkhtmltopdf 0.12",
             creationDate="D:20260702154500")
    grupos = mesma_origem([a, b])
    assert len(grupos) == 1
    assert grupos[0]["campo_comum"] == "producer+author"


def test_mesma_origem_criacao_no_mesmo_minuto(tmp_path):
    """Producers/authors distintos, mas criação no MESMO minuto → grupo criacao_minuto."""
    a = _pdf(tmp_path / "a.pdf", author="Empresa A", producer="GerA", creationDate="D:20260701101512")
    b = _pdf(tmp_path / "b.pdf", author="Empresa B", producer="GerB", creationDate="D:20260701101559")
    grupos = mesma_origem([a, b])
    minuto = [g for g in grupos if g["campo_comum"] == "criacao_minuto"]
    assert len(minuto) == 1
    assert minuto[0]["valor"] == "202607011015"
    assert sorted(minuto[0]["grupo"]) == sorted([a, b])


# ═══════════════════════════════ mesma_origem (lib-independente, monkeypatch) ═══════════════════════════════
def test_mesma_origem_logica_sem_lib_de_pdf(monkeypatch):
    """A lógica de agrupamento é testável sem NENHUMA lib de PDF (fake de metadados_pdf)."""
    fake = {
        "p1": {"author": "Ana", "producer": "GerX", "creator": "", "creation": "D:20260701101010", "moddate": ""},
        "p2": {"author": "Ana", "producer": "GerX", "creator": "", "creation": "D:20260705120000", "moddate": ""},
        "p3": {"author": "", "producer": "", "creator": "", "creation": "", "moddate": ""},  # producer vazio: fora
        "p4": None,  # extração falhou (já logada) — fica fora sem quebrar
    }
    monkeypatch.setattr(pm, "metadados_pdf", lambda p: fake[p])
    grupos = pm.mesma_origem(["p1", "p2", "p3", "p4"])
    assert len(grupos) == 1
    assert grupos[0]["campo_comum"] == "producer+author"
    assert grupos[0]["grupo"] == ["p1", "p2"]
