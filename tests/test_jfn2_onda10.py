# -*- coding: utf-8 -*-
"""Testes da Onda 10 (Lex + instrumentos de mandato): minutas .docx com cláusula de honestidade."""
from __future__ import annotations

import os


def test_gera_minuta_docx_de_cada_tipo(tmp_path, monkeypatch):
    from compliance_agent import mandato
    monkeypatch.setattr(mandato, "_OUT", tmp_path)
    for tipo in ("requerimento", "representacao", "noticia_fato", "post"):
        r = mandato.gerar(tipo, "11.111.111/0001-11", precedente=False)
        assert r["ok"] is True and r["tipo"] == tipo
        assert os.path.exists(r["path_docx"]) and r["path_docx"].endswith(".docx")


def test_tipo_invalido():
    from compliance_agent.mandato import gerar
    assert gerar("xpto", "x")["ok"] is False


def test_clausula_honestidade_sempre_presente(tmp_path, monkeypatch):
    """INVARIANTE jurídico: diligência/representação, NUNCA afirmação de crime."""
    from compliance_agent import mandato
    monkeypatch.setattr(mandato, "_OUT", tmp_path)
    r = mandato.gerar("representacao", "obras na UG 270042", precedente=False)
    t = r["texto"]
    assert "presunção de legitimidade" in t
    assert "NÃO se afirma a prática de ilícito" in t
    assert "indícios" in t.lower()


def test_pedido_por_tipo(tmp_path, monkeypatch):
    from compliance_agent import mandato
    monkeypatch.setattr(mandato, "_OUT", tmp_path)
    assert "TCE-RJ" in mandato.gerar("representacao", "x", precedente=False)["texto"]
    assert "MP-RJ" in mandato.gerar("noticia_fato", "x", precedente=False)["texto"]
    assert "Executivo" in mandato.gerar("requerimento", "x", precedente=False)["texto"]


def test_capability_mandato_pronto():
    from compliance_agent.skilltree import SkillTree
    st = SkillTree()
    st.reload()
    cap = st.capacidades.get("instrumento_mandato")
    assert cap is not None and cap["status"] == "PRONTO" and cap["rota"] == "/api/mandato/minuta"
    assert st.validate() == []
