# -*- coding: utf-8 -*-
"""Testes do acúmulo de cargos (folha ALERJ ∩ folha do Estado). SQLite temporário, sem rede."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from compliance_agent import acumulo_cargos as AC
from compliance_agent.collectors import alerj_transparencia as A


def _seed_estado(p: Path):
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE registros_folha (id INTEGER, pessoa_id TEXT, cpf TEXT, nome TEXT,
        orgao_codigo TEXT, orgao_nome TEXT, cargo TEXT, vinculo TEXT, competencia TEXT,
        remuneracao_bruta REAL, remuneracao_liquida REAL, abonos REAL, descontos REAL, fonte TEXT, created_at TEXT)""")
    con.executemany("INSERT INTO registros_folha (nome,orgao_nome,cargo,competencia,remuneracao_bruta) VALUES (?,?,?,?,?)", [
        ("ANDRÉ LUIZ DOS SANTOS", "Defensoria Pública", "Analista", "2024-08", 43000.0),
        ("MARIA SOLITARIA", "Sec. Saúde", "Médica", "2024-01", 10000.0)])
    con.commit(); con.close()


def test_parsear_folha_pega_nome_e_cargo():
    txt = (" Folha de Pagamento de maio de 2026\n"
           " ANDRE LUIZ DOS SANTOS          ASSESSOR PARLAMENTAR I        -    3.752,95   9.382,36\n"
           " FULANO QUE SO TEM NA ALERJ      AUXILIAR IV                  -    418,72     2.249,08\n"
           " NOME   CARGO   -\n")  # linha de cabeçalho deve cair fora
    r = A.parsear_folha(txt)
    assert r["mes_ano"] == "Maio/2026"
    nomes = {i["nome"] for i in r["itens"]}
    assert "ANDRE LUIZ DOS SANTOS" in nomes
    andre = next(i for i in r["itens"] if i["nome"] == "ANDRE LUIZ DOS SANTOS")
    assert "ASSESSOR PARLAMENTAR" in andre["cargo"]


def test_cruzamento_detecta_acumulo(tmp_path: Path):
    p = tmp_path / "t.db"
    _seed_estado(p)
    # ingere folha ALERJ (André acumula; Fulano não está no Estado)
    AC.ingerir_folha([{"nome": "ANDRE LUIZ DOS SANTOS", "cargo": "ASSESSOR PARLAMENTAR I"},
                      {"nome": "FULANO SO ALERJ", "cargo": "AUXILIAR IV"}], "Maio/2026", db_path=p)
    r = AC.cruzar(db_path=p)
    assert r["ok"]
    assert r["n_alerj"] == 2 and r["n_acumulo"] == 1
    a = r["achados"][0]
    assert a["nome"] == "ANDRE LUIZ DOS SANTOS"          # acento normalizado casa "ANDRÉ"×"ANDRE"
    assert "Defensoria" in a["orgao_estado"]
    assert "acúmulo" in r["leitura"].lower()


def test_sem_folha_alerj_honesto(tmp_path: Path):
    p = tmp_path / "v.db"
    _seed_estado(p)
    AC.ingerir_folha([], "Maio/2026", db_path=p)
    r = AC.cruzar(db_path=p)
    assert r["n_acumulo"] == 0
