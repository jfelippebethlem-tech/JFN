# -*- coding: utf-8 -*-
"""Integração do montador de fichas: aferição objetiva (rebaixe), matriz S×V, redline e
fallback sem peer-diff (raridade NULL) — montar_ctx não pode quebrar nem mentir.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_relatorio_direcionamento_fichas.py -q
"""
from __future__ import annotations

import json
import sqlite3

from compliance_agent.editais import db as ed
from compliance_agent.reporting import relatorio_direcionamento as rd


def _con():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    ed.init_schema(con)
    con.execute("""CREATE TABLE pcrj_licitacoes (
        numero_controle_pncp TEXT, orgao_nome TEXT, orgao_cnpj TEXT, modalidade TEXT,
        valor_estimado REAL, data_abertura TEXT, situacao TEXT)""")
    return con


def _semear(con, nc, clausula_txt, subtipo, score, raridade=0.8, valor=1_000_000.0):
    con.execute("INSERT INTO edital_documento (numero_controle_pncp, objeto, valor_estimado, texto) "
                "VALUES (?,?,?,?)", (nc, "aquisição de material", valor, clausula_txt))
    con.execute("INSERT INTO pcrj_licitacoes VALUES (?,?,?,?,?,?,?)",
                (nc, "Secretaria X", "00000000000191", "Pregão Eletrônico", valor, "2026-06-01", "aberta"))
    cur = con.execute("INSERT INTO edital_clausula (numero_controle_pncp, eixo, subtipo, texto, assinatura) "
                      "VALUES (?,?,?,?,?)", (nc, "habilitacao_econ_financeira", subtipo, clausula_txt, f"x:{nc}"))
    clausula_id = cur.lastrowid
    cur = con.execute("INSERT INTO edital_cluster (assinatura_objeto, membros_json, tamanho, avaliavel) "
                      "VALUES ('material', ?, 4, 1)", (json.dumps([nc, "p1", "p2", "p3"]),))
    con.execute("INSERT INTO clausula_veredito (clausula_id, cluster_id, numero_controle_pncp, raridade, "
                "forca_e7, sumula, votos_json, score_final, veredito) VALUES (?,?,?,?,?,?,?,?,?)",
                (clausula_id, cur.lastrowid, nc, raridade, "forte", "Súmula TCU 275",
                 json.dumps({"proporcionalidade": {"voto": 8, "justificativa": "x", "citacao": ""}}),
                 score, "direcionamento"))


def test_violacao_objetiva_vai_para_ficha_com_matriz_e_redline():
    con = _con()
    _semear(con, "nc1", "Capital social mínimo de 30% (trinta por cento) do valor estimado.",
            "capital", 8)
    ctx = rd.montar_ctx(con)
    corpo = json.dumps(ctx["secoes"], ensure_ascii=False)
    assert "EXCEDE o teto legal" in corpo          # teste executado na ficha
    assert "Matriz de risco" in corpo              # matriz S×V presente
    assert "Redação conforme sugerida" in corpo    # redline determinístico presente


def test_exigencia_dentro_do_teto_e_rebaixada():
    con = _con()
    _semear(con, "nc2", "Capital social mínimo de 8% do valor estimado da contratação.", "capital", 8)
    ctx = rd.montar_ctx(con)
    titulos = [s["titulo"] for s in ctx["secoes"]]
    assert any("Rebaixados pela aferição objetiva" in t for t in titulos)
    # nenhuma ficha completa sobrou (o único achado foi rebaixado)
    assert not any(t.startswith("3. Achado") for t in titulos)


def test_raridade_nula_nao_quebra_e_declara_ausencia_de_pares():
    con = _con()
    _semear(con, "nc3", "será aceito exclusivamente equipamento da marca Cisco", "marca", 7,
            raridade=None)
    ctx = rd.montar_ctx(con)
    corpo = json.dumps(ctx["secoes"], ensure_ascii=False)
    assert "insuficiente para comparação entre pares" in corpo
    assert "força absoluta do catálogo E7" in corpo


def test_beneficiario_real_aparece_na_ficha():
    con = _con()
    _semear(con, "nc4", "Capital social mínimo de 30% do valor estimado.", "capital", 9)
    con.execute("UPDATE clausula_veredito SET vencedor_doc='ACME LTDA (11222333000181)', "
                "sinais_json='[\"sócio em comum com 2ª colocada\"]'")
    ctx = rd.montar_ctx(con)
    corpo = json.dumps(ctx["secoes"], ensure_ascii=False)
    assert "ACME LTDA" in corpo and "sócio em comum" in corpo
    assert "indisponível nesta base" not in corpo
