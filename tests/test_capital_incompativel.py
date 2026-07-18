# -*- coding: utf-8 -*-
"""capital_incompativel — capital irrisório frente ao volume recebido (fachada/subcapitalização)."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.cruzamentos_intel import capital_incompativel


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE empresas_cadastro (cnpj_basico TEXT PRIMARY KEY, razao_social TEXT,
        natureza_cod TEXT, capital_social REAL, porte_cod TEXT, porte_txt TEXT, fonte_mes TEXT);
    CREATE TABLE favorecido_resumo (favorecido_cpf TEXT, favorecido_nome TEXT, total_pago REAL, n_obs INTEGER);
    """)
    con.executemany("INSERT INTO empresas_cadastro (cnpj_basico,razao_social,capital_social) VALUES (?,?,?)", [
        ("11111111", "SHELL LTDA", 1000.0),      # cap R$1k, recebe R$5mi → 5000× → flagra
        ("22222222", "GRANDE LTDA", 10_000_000.0),  # capital robusto → não flagra
        ("33333333", "SEM CAP LTDA", 0.0),          # capital 0 = não declarado → não flagra
        ("44444444", "POUCO LTDA", 2000.0)])        # cap baixo mas recebeu pouco → não flagra
    con.executemany("INSERT INTO favorecido_resumo (favorecido_cpf,favorecido_nome,total_pago,n_obs) VALUES (?,?,?,?)", [
        ("11111111000111", "SHELL", 5_000_000.0, 3),
        ("22222222000122", "GRANDE", 50_000_000.0, 40),
        ("33333333000133", "SEM CAP", 8_000_000.0, 10),
        ("44444444000144", "POUCO", 300_000.0, 2)])   # < min_total
    con.commit()
    con.close()
    return p


def test_flagra_capital_irrisorio(db):
    d = capital_incompativel(db_path=db)
    assert d["ok"] is True and d["n"] == 1
    a = d["achados"][0]
    assert a["cnpj"] == "11111111000111" and a["capital"] == 1000.0
    assert a["total_recebido"] == 5_000_000.0 and a["razao"] == 5000


def test_capital_robusto_e_zero_nao_flagram(db):
    d = capital_incompativel(db_path=db)
    cnpjs = {a["cnpj"] for a in d["achados"]}
    assert "22222222000122" not in cnpjs          # capital alto
    assert "33333333000133" not in cnpjs          # capital 0 = não declarado (ambíguo)


def test_valor_abaixo_do_minimo_nao_flagra(db):
    d = capital_incompativel(db_path=db, min_total=1_000_000)
    assert all(a["cnpj"] != "44444444000144" for a in d["achados"])  # recebeu só R$300k


def test_sem_tabela_cadastro_e_honesto(tmp_path):
    p = str(tmp_path / "v.db")
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE favorecido_resumo (favorecido_cpf TEXT, favorecido_nome TEXT, total_pago REAL, n_obs INTEGER)")
    con.commit(); con.close()
    d = capital_incompativel(db_path=p)
    assert d["ok"] is False and "empresas_cadastro" in d["erro"]


def test_ressalva_capital_atual(db):
    d = capital_incompativel(db_path=db)
    assert "capital ATUAL" in d["ressalva"] and "Indício" in d["ressalva"]
