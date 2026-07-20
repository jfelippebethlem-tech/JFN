# -*- coding: utf-8 -*-
"""Capítulos novos do dossiê completo — cláusulas íntegra, veredito de fachada, suspeitas, SEI.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_capitulos_dossie.py -q
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from compliance_agent.editais.db import init_schema
from compliance_agent.reporting import capitulos_dossie as cap
from compliance_agent.reporting.neutralidade import termos_proibidos

CNPJ = "58229293000163"


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    init_schema(c)
    c.execute("CREATE TABLE pcrj_contratos (numero_controle_pncp TEXT, numero_compra TEXT, "
              "fornecedor_documento TEXT)")
    c.execute("CREATE TABLE pncp_resultado (certame TEXT, fornecedor_cnpj TEXT, ordem_classificacao INTEGER)")
    cert = "42498600000171-1-000001/2026"
    c.execute("INSERT INTO edital_documento (numero_controle_pncp, ano, orgao_cnpj) VALUES (?, 2026, 'x')", (cert,))
    c.execute("INSERT INTO pcrj_contratos (numero_controle_pncp, numero_compra, fornecedor_documento) "
              "VALUES ('c-2', ?, ?)", (cert, CNPJ))
    c.execute("INSERT INTO edital_clausula (numero_controle_pncp, eixo, subtipo, texto, trecho_fonte) "
              "VALUES (?, 'habilitacao', 'atestado_quantitativo', "
              "'Exige-se atestado de no mínimo 80% do quantitativo licitado.', 'item 10.2')", (cert,))
    cid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute("INSERT INTO clausula_veredito (clausula_id, numero_controle_pncp, score_final, veredito, "
              "sumula, raridade) VALUES (?, ?, 8, 'direcionamento', 'Súmula TCU 263', 0.9)", (cid, cert))
    # cláusula suspeita (score 4)
    c.execute("INSERT INTO edital_clausula (numero_controle_pncp, eixo, subtipo, texto) "
              "VALUES (?, 'habilitacao', 'visita_tecnica', 'Visita técnica obrigatória.')", (cert,))
    cid2 = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.execute("INSERT INTO clausula_veredito (clausula_id, numero_controle_pncp, score_final, veredito) "
              "VALUES (?, ?, 4, 'atipica')", (cid2, cert))
    c.commit()
    yield c
    c.close()


def test_clausulas_restritivas_transcreve_integra_e_sumula(con):
    sec = cap.secao_clausulas_restritivas(con, CNPJ)
    assert sec is not None
    assert "atestado de no mínimo 80%" in sec["html"]  # íntegra transcrita
    assert "parcelas de maior relevância" in sec["html"]  # súmula 263 verbatim
    assert "item 10.2" in sec["html"]  # trecho-fonte
    assert termos_proibidos(sec["html"]) == []  # neutro


def test_clausulas_none_sem_certame(con):
    assert cap.secao_clausulas_restritivas(con, "00000000000000") is None


def test_veredito_fachada_explicito():
    d = {"fantasma": {"score": 78, "classificacao": "FORTE",
                      "sinais": ["CNPJ aberto 2 meses antes do 1º contrato", "capital R$ 1.000 frente a R$ 5 mi"]}}
    sec = cap.secao_veredito_fachada(d)
    assert "78/100" in sec["html"] and "FORTE" in sec["html"]
    assert "capital R$ 1.000" in sec["html"]


def test_veredito_fachada_indisponivel_honesto():
    sec = cap.secao_veredito_fachada({})
    assert "INDISPONÍVEL" in sec["html"]


def test_suspeitas_registra_grau_medio(con):
    sec = cap.secao_suspeitas(con, CNPJ, {"red_flags": [{"grav": 2, "obs": "pesquisa de preços frágil"}]})
    assert sec is not None
    assert "visita_tecnica" in sec["html"]  # cláusula score 4 = suspeita
    assert "pesquisa de preços frágil" in sec["html"]


def test_sei_arvore_le_arquivo(tmp_path, monkeypatch):
    proc = "270006_012938_2025"
    pdir = tmp_path / proc
    (pdir / "texto").mkdir(parents=True)
    (pdir / "texto" / "005_parecer.txt").write_text("Parecer da PGE: recomenda-se a exclusão da exigência.")
    manifest = {"processo": proc, "docs": [
        {"i": 0, "titulo": "Despacho inicial", "fase": "tramitacao", "tipo": "despacho", "texto": None},
        {"i": 5, "titulo": "Parecer PGE", "fase": "controle", "tipo": "parecer", "texto": "texto/005_parecer.txt"}]}
    (pdir / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(cap, "_ARQUIVO_SEI", tmp_path)
    sec = cap.secao_sei_arvore([proc])
    assert sec is not None
    assert "Parecer PGE" in sec["html"]  # árvore
    assert "recomenda-se a exclusão" in sec["html"]  # recorte da íntegra
    assert termos_proibidos(sec["html"]) == []


def test_sei_arvore_none_sem_arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(cap, "_ARQUIVO_SEI", tmp_path)
    assert cap.secao_sei_arvore(["inexistente"]) is None
