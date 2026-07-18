# -*- coding: utf-8 -*-
"""retro_auditoria.avaliar_lift — valida detector contra gabarito objetivo (sanções); lift e circularidade."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent import retro_auditoria as RA


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE pncp_resultado (fornecedor_cnpj TEXT, item_descricao TEXT, unidade_medida TEXT,
        valor_unitario REAL, quantidade REAL, ordem_classificacao INTEGER, data_pub TEXT,
        orgao_nome TEXT, unidade_nome TEXT, certame TEXT);
    CREATE TABLE sancoes_federais (cpf_cnpj TEXT, nome TEXT, cadastro TEXT, categoria TEXT,
        data_inicio TEXT, data_fim TEXT, orgao TEXT);
    CREATE TABLE fantasma_score (cnpj TEXT PRIMARY KEY, razao_social TEXT, score INTEGER,
        classificacao TEXT, sinais_json TEXT, origem TEXT, avaliado_em TEXT);
    """)
    # universo: 10 fornecedores, 2 sancionados → taxa-base 20%
    for i in range(1, 11):
        con.execute("INSERT INTO pncp_resultado (fornecedor_cnpj, ordem_classificacao) VALUES (?,1)",
                    (f"{i:014d}",))
    for i in (1, 2):
        con.execute("INSERT INTO sancoes_federais VALUES (?,?,?,?,?,?,?)",
                    (f"{i:014d}", "S", "CEIS", "Impedimento", "2025-01-01", "2027-01-01", "CGU"))
    # fantasma_medio marca 2 CNPJs, ambos sancionados → taxa 100%, lift 5x, CIRCULAR
    con.execute("INSERT INTO fantasma_score (cnpj, classificacao) VALUES ('00000000000001','medio')")
    con.execute("INSERT INTO fantasma_score (cnpj, classificacao) VALUES ('00000000000002','medio')")
    con.commit()
    con.close()
    monkeypatch.setattr("compliance_agent.cruzamentos_intel.ler_cache_intel", lambda n: None)
    # detectores independentes vazios neste fixture (sem preço/etc.) → foco no fantasma circular
    return p


def test_lift_calcula_taxa_base_e_circularidade(db):
    d = RA.avaliar_lift(db)
    assert d["ok"] is True
    assert d["taxa_base"] == pytest.approx(0.20)      # 2/10
    fm = next(x for x in d["detectores"] if x["detector"] == "fantasma_medio")
    assert fm["n"] == 2 and fm["sancionados"] == 2
    assert fm["taxa"] == pytest.approx(1.0) and fm["lift"] == pytest.approx(5.0)
    assert fm["circular"] is True and fm["n_pequeno"] is True


def test_lift_ordena_independentes_antes_dos_circulares(db):
    d = RA.avaliar_lift(db)
    circ = [x["circular"] for x in d["detectores"]]
    # todos os não-circular vêm antes dos circular (ordenação estável)
    assert circ == sorted(circ)


def test_lift_universo_vazio_e_honesto(tmp_path, monkeypatch):
    p = str(tmp_path / "v.db")
    con = sqlite3.connect(p)
    con.executescript("CREATE TABLE pncp_resultado (fornecedor_cnpj TEXT);"
                       "CREATE TABLE sancoes_federais (cpf_cnpj TEXT, categoria TEXT);"
                       "CREATE TABLE fantasma_score (cnpj TEXT, classificacao TEXT);")
    con.commit(); con.close()
    monkeypatch.setattr("compliance_agent.cruzamentos_intel.ler_cache_intel", lambda n: None)
    d = RA.avaliar_lift(p)
    assert d["ok"] is False and "vazio" in d["erro"]


def test_lift_ressalva_presente(db):
    d = RA.avaliar_lift(db)
    assert "Indício" in d["ressalva"] and "parcial" in d["ressalva"].lower()
