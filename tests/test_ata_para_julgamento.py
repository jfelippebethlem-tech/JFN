# -*- coding: utf-8 -*-
"""Ponte ata_documento (PNCP) → certame_julgamento (editais/ata_para_julgamento).

Antes da ponte, ata coletada do PNCP era trilha morta: o texto ficava em `ata_documento` e a
família certame_ata do índice seguia INDISPONÍVEL. Aqui: ata sintética gravada como o coletor
grava → backfill → decisões extraídas (reuso do coletor_ata) e persistidas, com a doutrina de
diligência POR LICITANTE. Rodar:  .venv/bin/python -m pytest tests/test_ata_para_julgamento.py -q
"""
from __future__ import annotations

import sqlite3

from compliance_agent.editais.ata_para_julgamento import backfill, julgar_certame
from compliance_agent.editais.db import init_schema

_ATA = """
ATA DE SESSÃO PÚBLICA DE JULGAMENTO — PREGÃO ELETRÔNICO Nº 12/2025

A empresa ALFA SERVICOS LTDA, CNPJ 11.111.111/0001-11, foi INABILITADA por apresentar certidão
de regularidade fiscal vencida na data da sessão.

A empresa BETA COMERCIO LTDA, CNPJ 22.222.222/0001-22, foi HABILITADA e declarada VENCEDORA
do certame, com proposta de R$ 980.000,00.
"""

_CERTAME = "12345678000190-1-000012/2025"


def _con_com_ata(tmp_path) -> sqlite3.Connection:
    con = sqlite3.connect(tmp_path / "c.db")
    init_schema(con)
    con.execute("""CREATE TABLE IF NOT EXISTS ata_documento (
        certame TEXT NOT NULL, orgao_cnpj TEXT, titulo TEXT, fonte_texto TEXT,
        n_cnpj INTEGER, texto TEXT, coletado_em TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (certame, titulo))""")
    con.execute("INSERT INTO ata_documento (certame, titulo, fonte_texto, n_cnpj, texto) "
                "VALUES (?,?,?,?,?)", (_CERTAME, "Ata de Julgamento das Propostas", "pdf", 2, _ATA))
    con.commit()
    return con


def test_julgar_certame_extrai_e_persiste(tmp_path):
    con = _con_com_ata(tmp_path)
    agg = julgar_certame(con, _CERTAME)
    assert agg is not None
    # ALFA inabilitada por certidão vencida SEM diligência própria → violação de saneamento
    assert agg["violacoes_saneamento"] == 1
    row = con.execute("SELECT licitantes, inabilitados, vencedor_cnpj FROM certame_julgamento "
                      "WHERE certame=?", (_CERTAME,)).fetchone()
    assert row[0] == 2 and row[1] == 1 and row[2] == "22.222.222/0001-22"
    con.close()


def test_backfill_so_pendentes_e_idempotente(tmp_path):
    con = _con_com_ata(tmp_path)
    s1 = backfill(con)
    assert s1["candidatos"] == 1 and s1["persistidos"] == 1 and s1["certames"] == [_CERTAME]
    s2 = backfill(con)  # 2ª passada: já julgado → nada a fazer
    assert s2["candidatos"] == 0 and s2["persistidos"] == 0
    con.close()


def test_f_competicao_usa_contagem_da_ata(tmp_path):
    """3ª fonte de proponentes: a ata julgada (certame_julgamento.licitantes) torna a família
    competição APURÁVEL mesmo sem proposta_item/ordem PNCP — registro só do vencedor continua
    não provando licitante único (honestidade preservada)."""
    con = _con_com_ata(tmp_path)
    julgar_certame(con, _CERTAME)
    from compliance_agent.editais.indice_certame import _f_competicao
    fam = _f_competicao(con, _CERTAME, {"tem_ordem_alem_do_1o": False, "n_forn_ordem": 0})
    assert fam["apuravel"] is True
    flag = {f["flag"]: f for f in fam["flags"]}["poucos_licitantes"]
    assert flag["valor"] == 0.5  # 2 licitantes na ata → VALOR_DOIS_LICITANTES
    # sem ata nem proposta nem ordem → segue INDISPONÍVEL (não inventa zero)
    fam2 = _f_competicao(con, "OUTRO-CERTAME", {"tem_ordem_alem_do_1o": False, "n_forn_ordem": 0})
    assert fam2["apuravel"] is False
    con.close()


def test_ata_ilegivel_nao_grava(tmp_path):
    con = sqlite3.connect(tmp_path / "c.db")
    init_schema(con)
    con.execute("""CREATE TABLE ata_documento (certame TEXT, orgao_cnpj TEXT, titulo TEXT,
        fonte_texto TEXT, n_cnpj INTEGER, texto TEXT, PRIMARY KEY (certame, titulo))""")
    con.execute("INSERT INTO ata_documento (certame, titulo, texto) VALUES (?,?,?)",
                ("X-1", "Ata da Sessão", "ata de julgamento sem nenhum CNPJ nem decisão legível"))
    con.commit()
    s = backfill(con)
    assert s["persistidos"] == 0 and s["sem_resultado"] == 1
    assert con.execute("SELECT COUNT(*) FROM certame_julgamento").fetchone()[0] == 0
    con.close()
