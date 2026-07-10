# -*- coding: utf-8 -*-
"""Task 4 — favorecidos finais via documentos de empenho/pagamento."""
import json
from pathlib import Path

from compliance_agent.emendas import favorecidos

FIXDIR = Path(__file__).parent / "fixtures"
DOCS = json.loads((FIXDIR / "emenda_documentos.json").read_text())
DETALHE = json.loads((FIXDIR / "despesa_documento.json").read_text())


def test_escolher_documentos_prioriza_pagamento():
    escolhidos = favorecidos.escolher_documentos(DOCS, cap=25)
    assert escolhidos
    fases = {d["fase"] for d in escolhidos}
    # a emenda da fixture tem Pagamento? se tiver, só pagamento; senão empenho
    assert fases <= {"Pagamento", "Empenho"} and len(fases) == 1


def test_parse_documento_detalhe():
    row = favorecidos.parse_documento_detalhe("202537240001", DETALHE)
    assert row["codigo_emenda"] == "202537240001"
    assert row["documento_favorecido"] == "06083453000105"     # só dígitos
    assert row["nome_favorecido"].startswith("FUNDO DE SAUDE")
    assert row["fase"] == "Empenho"
    assert row["documento_ref"] == "257001000012025NE452515"
    assert row["valor"] == 200.0


def test_parse_documento_detalhe_cpf_mascarado():
    det = dict(DETALHE, codigoFavorecido="***.123.456-**", nomeFavorecido="FULANO")
    row = favorecidos.parse_documento_detalhe("X", det)
    assert "123456" in row["documento_favorecido"] and row["documento_favorecido"].startswith("***")
