# -*- coding: utf-8 -*-
"""cadastro_enrich_sweep — alvo por valor sem cadastro; upsert do registro completo."""
from __future__ import annotations

import sqlite3

from tools import cadastro_enrich_sweep as CE


def _db(tmp_path):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.execute(CE._DDL)
    con.execute("""CREATE TABLE favorecido_resumo (favorecido_cpf TEXT, favorecido_nome TEXT,
        total_pago REAL, n_obs INTEGER)""")
    return p, con


def test_alvos_prioriza_valor_e_ignora_ja_cadastrado(tmp_path):
    p, con = _db(tmp_path)
    con.executemany("INSERT INTO favorecido_resumo (favorecido_cpf,total_pago) VALUES (?,?)", [
        ("11111111000111", 5_000_000), ("22222222000122", 2_000_000),
        ("33333333000133", 50_000),  # abaixo do min_valor
        ("44444444000144", 9_000_000)])
    # 44... já tem cadastro completo (situação preenchida) → não é alvo
    con.execute("INSERT INTO empresas (cnpj, situacao) VALUES ('44444444000144','ATIVA')")
    con.commit()
    alvos = CE._alvos(con, limite=10, min_valor=100_000)
    con.close()
    cnpjs = [c for c, _ in alvos]
    assert cnpjs == ["11111111000111", "22222222000122"]   # por valor desc, sem o 33 (baixo) nem 44 (pronto)


def test_upsert_grava_situacao_endereco_abertura(tmp_path):
    p, con = _db(tmp_path)
    CE._upsert(con, "11111111000111", {
        "razao_social": "ACME LTDA", "situacao": "ATIVA", "abertura": "2010-05-01",
        "logradouro": "RUA X", "numero": "10", "bairro": "CENTRO", "municipio": "RIO",
        "uf": "RJ", "cep": "20000000", "capital": "50000", "porte": "MICRO EMPRESA"})
    con.commit()
    r = dict(zip([c[1] for c in con.execute("PRAGMA table_info(empresas)")],
                 con.execute("SELECT * FROM empresas WHERE cnpj='11111111000111'").fetchone()))
    con.close()
    assert r["situacao"] == "ATIVA" and r["data_abertura"] == "2010-05-01"
    assert r["municipio"] == "RIO" and r["capital_social"] == 50000.0
    assert "RUA X" in r["raw_json"]


def test_upsert_e_idempotente_e_completa(tmp_path):
    p, con = _db(tmp_path)
    con.execute("INSERT INTO empresas (cnpj, razao_social) VALUES ('11111111000111','ANTIGA')")
    con.commit()
    CE._upsert(con, "11111111000111", {"situacao": "BAIXADA", "abertura": "2005-01-01",
                                       "municipio": "NITEROI", "uf": "RJ", "cep": "24000000"})
    con.commit()
    r = con.execute("SELECT situacao, municipio, razao_social FROM empresas "
                    "WHERE cnpj='11111111000111'").fetchone()
    con.close()
    assert r[0] == "BAIXADA" and r[1] == "NITEROI" and r[2] == "ANTIGA"  # razão preservada (COALESCE)
