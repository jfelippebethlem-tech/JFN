# -*- coding: utf-8 -*-
"""Teste do gap incremental do backfill de verificação de endereço (determinístico, temp DB)."""
import sqlite3

import tools.backfill_verificacao_endereco as mod


def _db(tmp_path):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE endereco_fornecedor (cnpj TEXT PRIMARY KEY, razao TEXT, endereco TEXT, "
                "endereco_norm TEXT, municipio TEXT, uf TEXT, cep TEXT)")
    con.executemany("INSERT INTO endereco_fornecedor VALUES (?,?,?,?,?,?,?)", [
        ("11222333000181", "A", "RUA X, 1", "rua x 1", "Rio de Janeiro", "RJ", "20000000"),
        ("44555666000172", "B", "RUA Y, 2", "rua y 2", "Niterói", "RJ", "24000000"),
        ("77888999000160", "C", "", "", "", "", ""),  # sem endereço → fora do gap
    ])
    con.execute(mod._DDL)
    # já verificado um deles → deve sair do gap
    con.execute("INSERT INTO endereco_verificacao VALUES (?,?,?,?,?,?,?,?,?)",
                ("11222333000181", "AFASTADO", "BAIXO", 1, -22.9, -43.2, "Rio de Janeiro", "ok", "2026-06-11"))
    con.commit()
    return con


def test_gap_pula_verificados_e_sem_endereco(tmp_path):
    con = _db(tmp_path)
    gap = mod._gap(con, None, 0)
    cnpjs = {g["cnpj"] for g in gap}
    assert cnpjs == {"44555666000172"}  # 11.. já verificado; 77.. sem endereço
    con.close()


def test_gap_respeita_limite(tmp_path):
    con = _db(tmp_path)
    # remove a verificação p/ haver 2 no gap, e limita a 1
    con.execute("DELETE FROM endereco_verificacao")
    con.commit()
    assert len(mod._gap(con, None, 1)) == 1
    assert len(mod._gap(con, None, 0)) == 2
    con.close()
