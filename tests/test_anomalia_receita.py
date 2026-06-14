# -*- coding: utf-8 -*-
"""
Testes da função pura `anomalia_receita.anomalias_orgao` — cruzamento dump da Receita × fornecedores.

Constrói um DB SQLite isolado (via env JFN_DB, fixture `_isola_db` do conftest) com um mini-universo
determinístico e verifica cada anomalia (sem-fins, rede/grupo, veículo de aluguel, sócio-único) +
cobertura honesta + degradação quando o dump não está ingerido. SEM rede (cadastro fica off por default).
"""
from __future__ import annotations

import os
import sqlite3

import pytest

from compliance_agent.reporting import anomalia_receita as ar


def _seed(db_path: str) -> None:
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE ordens_bancarias (
            id INTEGER PRIMARY KEY, ug_codigo TEXT, favorecido_cpf TEXT,
            favorecido_nome TEXT, valor REAL
        );
        CREATE TABLE empresas_min (cnpj_basico TEXT PRIMARY KEY, razao_social TEXT, natureza_cod TEXT, fonte_mes TEXT);
        CREATE TABLE socios_receita (
            cnpj_basico TEXT, ident TEXT, nome_socio TEXT, nome_norm TEXT, doc_socio TEXT,
            qualificacao_cod TEXT, qualificacao_txt TEXT, data_entrada TEXT, faixa_etaria TEXT, fonte_mes TEXT
        );
        CREATE TABLE socios_reverso (
            doc_socio TEXT, nome_socio TEXT, nome_norm TEXT, cnpj_basico TEXT, qualif_cod TEXT, fonte_mes TEXT
        );
        """
    )
    UG = "099900"
    # fornecedores (raiz de 8 díg + filial 0001 + DV 99):
    #  11111111 = ASSOCIACAO X (sem fins, 3999, alto valor)  -> anomalia 1 + 3 (sócio único)
    #  22222222 = FUNDACAO EDU (sem fins, 3069, "universidade" -> ressalva)
    #  33333333 = ALFA LTDA (natureza 2062, alto valor, 1 sócio) -> anomalia 3
    #  44444444 = BETA LTDA (natureza 2062, 2 sócios)
    #  55555555 = ENTE PUBLICO (natureza 1023) -> NÃO anomalia
    obs = [
        (UG, "11111111000199", "ASSOCIACAO X", 80_000_000.0),
        (UG, "22222222000199", "FUNDACAO EDU UNIVERSIDADE", 9_000_000.0),
        (UG, "33333333000199", "ALFA LTDA", 30_000_000.0),
        (UG, "44444444000199", "BETA LTDA", 2_000_000.0),
        (UG, "55555555000199", "ENTE PUBLICO", 12_000_000.0),
        ("000000", "33333333000199", "ALFA LTDA (outra UG)", 1.0),  # ruído de outra UG
    ]
    con.executemany(
        "INSERT INTO ordens_bancarias (ug_codigo,favorecido_cpf,favorecido_nome,valor) VALUES (?,?,?,?)", obs
    )
    con.executemany(
        "INSERT INTO empresas_min (cnpj_basico,razao_social,natureza_cod,fonte_mes) VALUES (?,?,?,?)",
        [
            ("11111111", "ASSOCIACAO X", "3999", "2026-05"),
            ("22222222", "FUNDACAO EDU UNIVERSIDADE", "3069", "2026-05"),
            ("33333333", "ALFA LTDA", "2062", "2026-05"),
            ("44444444", "BETA LTDA", "2062", "2026-05"),
            ("55555555", "ENTE PUBLICO", "1023", "2026-05"),
        ],
    )
    # QSA: JOAO administra ALFA e BETA (2 fornecedores do MESMO órgão -> anomalia 2a)
    #      ALFA tem só 1 sócio (JOAO) -> anomalia 3 ; ASSOCIACAO X tem 1 sócio (PRESIDENTE)
    soc = [
        ("11111111", "2", "MARIA PRES", "maria pres", "***111111**", "16", "Presidente", "", "", "2026-05"),
        ("33333333", "2", "JOAO ADM", "joao adm", "***222222**", "49", "Sócio-Administrador", "", "", "2026-05"),
        ("44444444", "2", "JOAO ADM", "joao adm", "***222222**", "49", "Sócio-Administrador", "", "", "2026-05"),
        ("44444444", "2", "PEDRO SOCIO", "pedro socio", "***333333**", "22", "Sócio", "", "", "2026-05"),
    ]
    con.executemany(
        "INSERT INTO socios_receita (cnpj_basico,ident,nome_socio,nome_norm,doc_socio,"
        "qualificacao_cod,qualificacao_txt,data_entrada,faixa_etaria,fonte_mes) VALUES (?,?,?,?,?,?,?,?,?,?)",
        soc,
    )
    # reverso: JOAO aparece em 12 CNPJs no Brasil -> veículo de aluguel (>=10)
    rev = [("***222222**", "JOAO ADM", "joao adm", f"9000000{i:01d}", "49", "2026-05") for i in range(12)]
    con.executemany(
        "INSERT INTO socios_reverso (doc_socio,nome_socio,nome_norm,cnpj_basico,qualif_cod,fonte_mes) "
        "VALUES (?,?,?,?,?,?)",
        rev,
    )
    con.commit()
    con.close()


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    p = tmp_path / "anom.db"
    monkeypatch.setenv("JFN_DB", str(p))
    _seed(str(p))
    return str(p)


def test_ok_e_cobertura(_db):
    out = ar.anomalias_orgao("099900")
    assert out["ok"] is True
    assert out["ug"] == "099900"
    cov = out["cobertura"]
    assert cov["n_fornecedores_pj"] == 5
    assert cov["n_no_empresas_min"] == 5
    assert cov["pct_empresas_min"] == 100.0


def test_anomalia_sem_fins_com_ressalva(_db):
    out = ar.anomalias_orgao("099900")
    sf = {r["razao_social"]: r for r in out["sem_fins_lucrativos"]}
    assert "ASSOCIACAO X" in sf and sf["ASSOCIACAO X"]["ressalva"] is False
    # natureza educacional ("universidade") recebe ressalva True
    assert sf["FUNDACAO EDU UNIVERSIDADE"]["ressalva"] is True
    # ente público (natureza 1xxx) NÃO entra
    assert "ENTE PUBLICO" not in sf


def test_anomalia_rede_mesmo_orgao(_db):
    out = ar.anomalias_orgao("099900")
    nomes = {r["nome_socio"]: r for r in out["rede_mesmo_orgao"]}
    assert "JOAO ADM" in nomes
    assert nomes["JOAO ADM"]["n_fornecedores"] == 2  # ALFA + BETA


def test_anomalia_veiculo_de_aluguel(_db):
    out = ar.anomalias_orgao("099900")
    vs = {r["nome_socio"]: r for r in out["veiculos_aluguel"]}
    assert vs["JOAO ADM"]["n_cnpjs_brasil"] == 12


def test_anomalia_socio_unico_alto_valor(_db):
    out = ar.anomalias_orgao("099900", valor_alto=5_000_000.0)
    nomes = {r["razao_social"] for r in out["socio_unico_alto_valor"]}
    assert "ALFA LTDA" in nomes          # 30M, 1 sócio
    assert "ASSOCIACAO X" in nomes       # 80M, 1 sócio (presidente)
    assert "BETA LTDA" not in nomes      # 2 sócios -> não entra


def test_indicio_true(_db):
    assert ar.anomalias_orgao("099900")["indicio"] is True


def test_degrada_sem_dump(tmp_path, monkeypatch):
    p = tmp_path / "vazio.db"
    con = sqlite3.connect(str(p))
    con.execute("CREATE TABLE ordens_bancarias (id INTEGER PRIMARY KEY, ug_codigo TEXT, "
                "favorecido_cpf TEXT, favorecido_nome TEXT, valor REAL)")
    con.commit(); con.close()
    monkeypatch.setenv("JFN_DB", str(p))
    out = ar.anomalias_orgao("099900")
    assert out["ok"] is False
    assert "não ingerido" in out["_nota"]


def test_ug_vazia():
    assert ar.anomalias_orgao("")["ok"] is False
