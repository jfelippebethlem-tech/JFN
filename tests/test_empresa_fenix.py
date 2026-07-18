# -*- coding: utf-8 -*-
"""empresa_fenix — empresa BAIXADA/INAPTA que recebeu (valor de favorecido_resumo, situação case-insens.)."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.cruzamentos_intel import empresa_fenix


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE empresas (cnpj TEXT, razao_social TEXT, data_abertura TEXT, situacao TEXT);
    CREATE TABLE favorecido_resumo (favorecido_cpf TEXT, favorecido_nome TEXT, total_pago REAL, n_obs INTEGER);
    CREATE TABLE ob_orcamentaria_siafe (credor TEXT, valor REAL, data_emissao TEXT);
    """)
    con.executemany("INSERT INTO empresas VALUES (?,?,?,?)", [
        ("11111111000111", "MORTA LTDA", "2005-01-01", "BAIXADA"),
        ("22222222000122", "MINUSCULA LTDA", "2005-01-01", "Inapta"),   # case minúsculo
        ("33333333000133", "VIVA LTDA", "2005-01-01", "ATIVA"),          # ativa, não recém → não entra
        ("44444444000144", "CONSORCIO ABC SPE", "2024-06-01", "ATIVA"),  # SPE recém → excluída
        ("55555555000155", "RECEM LTDA", "2025-06-01", "ATIVA"),         # aberta ≤12m antes da 1ª OB
    ])
    con.executemany("INSERT INTO favorecido_resumo (favorecido_cpf,total_pago,n_obs) VALUES (?,?,?)", [
        ("11111111000111", 500000.0, 10), ("22222222000122", 90000.0, 3),
        ("33333333000133", 9_000_000.0, 50), ("44444444000144", 8_000_000.0, 5),
        ("55555555000155", 1_000_000.0, 4)])
    # 1ª OB de RECEM em 2025-08 (aberta 2025-06 → 2 meses) → recém_aberta
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('55555555000155', 100000, '10/08/2025')")
    con.commit()
    con.close()
    return p


def test_defunta_baixada_e_inapta_case_insensitive(db):
    d = empresa_fenix(db_path=db)
    assert d["ok"] is True
    tipos = {a["cnpj"]: a["tipo"] for a in d["achados"]}
    assert tipos.get("11111111000111") == "defunta"       # BAIXADA
    assert tipos.get("22222222000122") == "defunta"       # 'Inapta' (minúsculo) reconhecido
    assert d["n_defunta"] == 2
    # valor vem de favorecido_resumo (TFE incluso), não só OB SIAFE
    morta = next(a for a in d["achados"] if a["cnpj"] == "11111111000111")
    assert morta["total_recebido"] == 500000.0 and morta["n_obs"] == 10


def test_ativa_regular_nao_entra_e_spe_excluida(db):
    d = empresa_fenix(db_path=db)
    cnpjs = {a["cnpj"] for a in d["achados"]}
    assert "33333333000133" not in cnpjs                  # ATIVA regular
    assert "44444444000144" not in cnpjs                  # SPE (excluída mesmo recém)


def test_recem_aberta_dispara(db):
    d = empresa_fenix(db_path=db)
    recem = [a for a in d["achados"] if a["tipo"] == "recem_aberta"]
    assert any(a["cnpj"] == "55555555000155" for a in recem)


def test_total_defunta_e_ressalva_temporal(db):
    d = empresa_fenix(db_path=db)
    assert d["total_defunta"] == pytest.approx(590000.0)  # 500k + 90k
    assert "APÓS o pagamento" in d["ressalva"] and "Indício" in d["ressalva"]
