# -*- coding: utf-8 -*-
"""Onda G — índice COMPACTO da varredura SEI (SQLite dedicado; persiste só dado estruturado)."""
from __future__ import annotations


def test_persistir_e_stats(tmp_path, monkeypatch):
    from compliance_agent.sei import indice
    monkeypatch.setattr(indice, "_DB", tmp_path / "sei_indice.db")
    r = indice.persistir(
        "SEI-270060/002569/2022", objeto="Aquisição de insumos", tipo_processo="contratacao",
        docs=[{"titulo": "Nota de Empenho - NE", "tipo": "empenho", "formato": "html", "url": "u1"}],
        relacionados=[{"numero": "SEI-270060/000123/2022", "titulo": "Pregão SRP", "url": "u9"}],
        itens=[{"doc": "Planilha", "tipo_doc": "planilha_preco", "descricao": "Cânula",
                "valor_unitario": 12.5, "cnpj": "11222333000144", "metodo": "llm_texto", "confianca": 0.8}])
    assert r["n_docs"] == 1 and r["n_relacionados"] == 1 and r["n_itens"] == 1
    assert indice.ja_indexado("SEI-270060/002569/2022") is True
    assert indice.ja_indexado("SEI-000/000/0000") is False
    s = indice.stats()
    assert s["processos"] == 1 and s["ok"] == 1 and s["itens_preco"] == 1 and s["relacionados"] == 1


def test_idempotente(tmp_path, monkeypatch):
    from compliance_agent.sei import indice
    monkeypatch.setattr(indice, "_DB", tmp_path / "sei_indice.db")
    for _ in range(3):
        indice.persistir("P1", docs=[{"url": "x", "titulo": "t"}])
    # reprocessar não duplica
    assert indice.stats()["processos"] == 1
    import sqlite3
    c = sqlite3.connect(str(tmp_path / "sei_indice.db"))
    assert c.execute("SELECT COUNT(*) FROM sei_documento WHERE processo='P1'").fetchone()[0] == 1
    c.close()
