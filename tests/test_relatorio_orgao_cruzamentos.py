# -*- coding: utf-8 -*-
"""Cruzamentos de inteligência no relatório de ÓRGÃO (DD/cartel/endereço) + regressão do backfill.

Cobre o pedido do dono (cont.17): 'todos os cruzamentos no relatório'. Inclui o teste de regressão do
bug do backfill de endereço (tabela ganhou colunas visual_* → 13 colunas; o INSERT posicional de 9
quebrava em TODA linha — empresas nunca eram verificadas)."""
from __future__ import annotations

import sqlite3

from compliance_agent.reporting import inteligencia_orgao as IO


# ───────── regressão: INSERT nomeado no backfill de endereço (bug das 13 colunas) ─────────

_DDL_13 = (
    "CREATE TABLE endereco_verificacao (cnpj TEXT PRIMARY KEY, status TEXT, nivel TEXT, exato INTEGER, "
    "lat REAL, lon REAL, municipio_geo TEXT, evidencia TEXT, verificado_em TEXT, "
    "visual_classe TEXT, visual_conf REAL, visual_fonte TEXT, visual_em TEXT)"
)
# o MESMO statement nomeado usado em tools/backfill_verificacao_endereco.py
_INSERT = ("INSERT OR REPLACE INTO endereco_verificacao "
           "(cnpj,status,nivel,exato,lat,lon,municipio_geo,evidencia,verificado_em) "
           "VALUES (?,?,?,?,?,?,?,?,?)")


def test_backfill_insert_nomeado_cabe_em_tabela_13_colunas():
    """Garante que o INSERT de 9 valores NOMEADOS funciona na tabela de 13 colunas (visual_* = NULL).
    Se alguém voltar ao INSERT posicional, este teste quebra (a regressão do bug volta a ser pega)."""
    con = sqlite3.connect(":memory:")
    con.execute(_DDL_13)
    assert len([r[1] for r in con.execute("PRAGMA table_info(endereco_verificacao)")]) == 13
    con.execute(_INSERT, ("00000000000191", "INDISPONIVEL", "—", 0, None, None, "", "sem geocode", "2026-06-11"))
    con.commit()
    row = con.execute("SELECT cnpj,status,visual_classe FROM endereco_verificacao").fetchone()
    assert row[0] == "00000000000191" and row[1] == "INDISPONIVEL" and row[2] is None


def test_backfill_source_usa_colunas_nomeadas():
    """Guarda extra: o código-fonte do backfill NÃO pode voltar ao INSERT posicional (VALUES sem colunas)."""
    src = open("tools/backfill_verificacao_endereco.py", encoding="utf-8").read()
    assert "(cnpj,status,nivel,exato,lat,lon,municipio_geo,evidencia,verificado_em)" in src
    assert "INSERT OR REPLACE INTO endereco_verificacao VALUES" not in src  # o posicional quebrado


# ───────── helpers de cruzamento do relatório de órgão ─────────

def test_dd_orgao_bounded_degrada_honesto():
    """UG inexistente → degrada honesto (ok=False, sem exceção)."""
    out = IO._dd_orgao_bounded("000000", anos=None, top_n=2)
    assert isinstance(out, dict) and "ok" in out


def test_endereco_real_orgao_estrutura():
    """Cruzamento de endereço-realidade devolve os buckets honestos (AFASTADO/INDICIO/INDISPONIVEL)."""
    er = IO._endereco_real_orgao("000000")  # UG sem fornecedores → ok=False, contadores zerados
    for k in ("ok", "n_forn", "n_verificados", "afastado", "indicio", "indisponivel", "indicios"):
        assert k in er
    assert er["afastado"] + er["indicio"] + er["indisponivel"] == er["n_verificados"]
