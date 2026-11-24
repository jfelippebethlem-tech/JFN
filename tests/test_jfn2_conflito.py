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
        CREATE TABLE ob_orcamentaria_siafe (credor TEXT, valor REAL, status TEXT, ug_pagadora TEXT,
            ug_emitente TEXT, processo TEXT);
        """
    )
    # Empresa fornecedora com OB PAGA no SIAFE (24/11/2026: o espelho TFE deixou de ser fonte do conflito)
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?)",
                ("11222333000199", 500000.0, "Contabilizado", "100100", "100100", None))
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
    monkeypatch.setenv("JFN_DB", str(db))  # _resolver_db() lê JFN_DB em call-time (refactor cont.36)

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


def test_conflito_homonimo_de_cpf_diferente_e_mascara_sem_nome_nao_entram(tmp_path, monkeypatch):
    """19/11/2026 — régua `identidade_pessoa`: nome igual com CPF divergente é homônimo; sócio sem documento é
    indeterminado; a máscara coincidente com NOME diferente não identifica ninguém. Nenhum dos três é achado."""
    db = tmp_path / "c.db"
    _db_sintetico(str(db))
    con = sqlite3.connect(db)
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?)",
                ("44555666000199", 900000.0, "Contabilizado", "100100", "100100", None))
    con.executemany("INSERT INTO socios_fornecedor VALUES (?,?,?,?,?,?,?)", [
        ("44555666000199", "EMPRESA Y", "Maria Homonima", "MARIA HOMONIMA", "***111111**", "Socio", "2026"),
        ("44555666000199", "EMPRESA Y", "Pedro Semdoc", "PEDRO SEMDOC", "", "Socio", "2026"),
        ("44555666000199", "EMPRESA Y", "Outro Nome", "OUTRO NOME", "***777888**", "Socio", "2026")])
    con.executemany("INSERT INTO doacoes_eleitorais VALUES (?,?,?,?,?,?)", [
        ("22233344455", "Maria Homonima", "C1", "P", 2022, 500.0),     # CPF dígitos 4–9 = 334445 ≠ 111111
        ("55566677788", "Pedro Semdoc", "C1", "P", 2022, 500.0),       # sócio sem documento
        ("12377788899", "Fulano Diferente", "C1", "P", 2022, 500.0)])  # máscara 777888 bate, nome não
    con.commit(); con.close()
    monkeypatch.setenv("JFN_DB", str(db))
    r = lc.conflito()
    assert not any(x["empresa_cnpj"] == "44555666000199" for x in r["rede"]), r["rede"]
    assert r["homonimos_descartados"] == 1 and r["indeterminados_sem_doc"] == 1
    # o positivo continua: nome + CPF conferido
    ok = next(x for x in r["rede"] if x["empresa_cnpj"] == "11222333000199")
    assert ok["selo"] == "VERIFICADO" and "6 dígitos" in ok["motivo"]


def test_conflito_espelho_tfe_sozinho_nao_e_pagamento(tmp_path, monkeypatch):
    """Controle negativo (24/11/2026): empresa que só aparece no espelho TFE, sem OB paga no SIAFE, não entra na rede;
    e o total da que entra é o pago do SIAFE, sem somar o espelho (antes: n_ob = TFE + SIAFE, total = só TFE)."""
    db = tmp_path / "c.db"
    _db_sintetico(str(db))
    con = sqlite3.connect(db)
    con.execute("INSERT INTO ordens_bancarias VALUES (?,?)", ("11222333000199", 7_000_000.0))   # espelho: ignorado
    con.commit(); con.close()
    monkeypatch.setenv("JFN_DB", str(db))
    r = lc.conflito()
    x = [v for v in r["rede"] if v["empresa_cnpj"] == "11222333000199"]
    assert x and x[0]["total_ob"] == 500000.0 and x[0]["n_ob"] == 1

