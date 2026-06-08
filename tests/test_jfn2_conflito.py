# -*- coding: utf-8 -*-
"""Onda 2 — conflito doador↔SÓCIO↔contrato (requisito-chave do dono). Testa o cruzamento via QSA com
CPF mascarado, usando um DB sintético (não depende do TSE real)."""
from __future__ import annotations

import sqlite3

import compliance_agent.lex_conflito as lc


def _db_sintetico(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE doacoes_eleitorais (cpf_cnpj_doador TEXT, nome_doador TEXT, nome_candidato TEXT,
            partido TEXT, ano_eleicao INT, valor REAL);
        CREATE TABLE socios_fornecedor (cnpj TEXT, razao TEXT, socio_nome TEXT, socio_nome_norm TEXT,
            socio_doc TEXT, qualificacao TEXT, ingerido_em TEXT);
        CREATE TABLE ordens_bancarias (favorecido_cpf TEXT, valor REAL);
        CREATE TABLE ob_orcamentaria_siafe (credor TEXT);
        """
    )
    # Empresa fornecedora com OB
    con.execute("INSERT INTO ordens_bancarias VALUES (?,?)", ("11222333000199", 500000.0))
    # Sócio dessa empresa: nome + CPF mascarado (padrão QSA ***DDDDDD**)
    con.execute("INSERT INTO socios_fornecedor VALUES (?,?,?,?,?,?,?)",
                ("11222333000199", "EMPRESA X", "Joao Da Silva", "JOAO DA SILVA", "***456789**", "Socio", "2026"))
    # Doador no TSE = esse sócio (CPF completo 123.456.789-01 -> mascara ***456789**) doando a um candidato
    con.execute("INSERT INTO doacoes_eleitorais VALUES (?,?,?,?,?,?)",
                ("12345678901", "Joao Da Silva", "FULANO CANDIDATO", "XX", 2022, 25000.0))
    # Doador irrelevante (não é sócio de ninguém com OB)
    con.execute("INSERT INTO doacoes_eleitorais VALUES (?,?,?,?,?,?)",
                ("99999999999", "Zé Ninguem", "OUTRO", "YY", 2022, 1000.0))
    con.commit(); con.close()


def test_conflito_via_socio(tmp_path, monkeypatch):
    db = tmp_path / "c.db"
    _db_sintetico(str(db))
    monkeypatch.setattr(lc, "_DB", db)

    r = lc.conflito()
    assert r["ok"] is True
    rede = r["rede"]
    # deve achar o vínculo via SÓCIO (não direto), corroborado por nome + cpf mascarado
    assert any(x["via"] == "socio" and x["empresa_cnpj"] == "11222333000199" for x in rede), rede
    achado = next(x for x in rede if x["empresa_cnpj"] == "11222333000199")
    assert "nome_socio" in achado["sinais"] and "cpf_mascarado" in achado["sinais"]
    assert achado["valor_doacao"] == 25000.0 and achado["total_ob"] == 500000.0
    # o doador irrelevante não entra
    assert not any(x["doador"] == "Zé Ninguem" for x in rede)
