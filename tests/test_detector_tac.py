# -*- coding: utf-8 -*-
"""Testes do detector determinístico RF-TAC (pagamento fora de contrato regular via TAC/indenização).

Puros (medir_tac sobre linhas, sem DB) + integração contra um DB tmp descartável (tac_por_cnpj/por_ug/
red_flag_tac). Cobrem a regex, o cálculo do %, a honestidade do INDISPONÍVEL e as faixas de severidade.
"""
import sqlite3

from compliance_agent.reporting.detector_tac import (
    medir_tac, red_flag_tac, tac_por_cnpj, tac_por_ug, _RX_TAC, _severidade,
)


# ───────────────────────── regex ─────────────────────────

def test_regex_casa_variantes():
    assert _RX_TAC.search("PG DO TERMO DE AJUSTE DE CONTAS - INDENIZAÇÃO")
    assert _RX_TAC.search("indenizacao dos servicos")
    assert _RX_TAC.search("RECONHECIMENTO DE DIVIDA")
    assert _RX_TAC.search("reconhec. de dívida")
    assert not _RX_TAC.search("pagamento de contrato regular 123/2024")
    assert not _RX_TAC.search("nota fiscal de servico continuo")


# ───────────────────────── núcleo puro ─────────────────────────

def test_medir_tac_percentual():
    m = medir_tac([(100.0, "PG TERMO DE AJUSTE DE CONTAS"),
                   (100.0, "contrato 123"),
                   (50.0, "indenizacao")])
    assert m["total"] == 250.0
    assert m["total_tac"] == 150.0
    assert m["pct"] == 60.0
    assert m["n_tac"] == 2


def test_medir_tac_aceita_dict():
    m = medir_tac([{"valor": 10.0, "observacao": "INDENIZ"}, {"valor": 90.0, "observacao": "contrato"}])
    assert m["pct"] == 10.0


def test_medir_tac_indisponivel_sem_observacao():
    # nenhuma OB com texto → pct 0 MAS cobertura INDISPONIVEL (≠ "limpo")
    m = medir_tac([(10.0, None), (20.0, "")])
    assert m["pct"] == 0.0
    assert "INDISPONIVEL" in m["cobertura"]


def test_medir_tac_vazio():
    m = medir_tac([])
    assert m["pct"] == 0.0 and m["n"] == 0
    assert "INDISPONIVEL" in m["cobertura"]


def test_medir_tac_parcial_sem_obs_conta_no_denominador():
    # OB sem texto entra no total (denominador) mas não pode virar TAC — honesto
    m = medir_tac([(100.0, "INDENIZACAO"), (100.0, None)])
    assert m["total"] == 200.0
    assert m["total_tac"] == 100.0
    assert m["pct"] == 50.0
    assert m["n_sem_obs"] == 1


# ───────────────────────── severidade ─────────────────────────

def test_severidade_faixas():
    assert _severidade(60.0, 1_000_000)[0] == "🔴"
    assert _severidade(35.0, 200_000_000)[0] == "🔴"      # %médio mas valor enorme
    assert _severidade(35.0, 1_000_000)[1] == "MEDIO"
    assert _severidade(12.0, 1_000_000)[1] == "BAIXO"


# ───────────────────────── integração com DB tmp ─────────────────────────

def _mkdb(path, linhas):
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE ordens_bancarias (favorecido_cpf TEXT, ug_codigo TEXT, "
                "ug_nome TEXT, valor REAL, observacao TEXT)")
    con.executemany("INSERT INTO ordens_bancarias VALUES (?,?,?,?,?)", linhas)
    con.commit()
    con.close()


def test_tac_por_cnpj_db(tmp_path):
    db = tmp_path / "t.db"
    _mkdb(db, [
        ("12345678000199", "294200", "FUNDO X", 100.0, "PG TERMO DE AJUSTE DE CONTAS"),
        ("12345678000199", "294200", "FUNDO X", 300.0, "contrato regular 1/2024"),
        ("99999999000100", "294200", "FUNDO X", 1000.0, "indenizacao"),
    ])
    m = tac_por_cnpj("12345678000199", db_path=db)
    assert m["pct"] == 25.0
    assert m["raiz"] == "12345678"


def test_tac_por_ug_db(tmp_path):
    db = tmp_path / "t.db"
    _mkdb(db, [
        ("11111111000111", "294200", "FUNDO X", 500.0, "INDENIZACAO"),
        ("22222222000122", "294200", "FUNDO X", 500.0, "contrato"),
    ])
    u = tac_por_ug("294200", db_path=db)
    assert u["pct"] == 50.0
    assert u["ug_nome"] == "FUNDO X"


def test_red_flag_tac_dispara_e_nao_dispara(tmp_path):
    db = tmp_path / "t.db"
    _mkdb(db, [
        ("33333333000133", "100100", "ORG", 5_000_000.0, "PG TERMO DE AJUSTE DE CONTAS - INDENIZACAO"),
        ("33333333000133", "100100", "ORG", 5_000_000.0, "contrato regular"),
        # fornecedor limpo
        ("44444444000144", "100100", "ORG", 1_000_000.0, "contrato regular 2/2024"),
    ])
    rf = red_flag_tac("33333333000133", db_path=db)
    assert rf is not None
    assert rf["codigo"] == "RF-TAC"
    assert rf["pct"] == 50.0
    assert rf["grau"] == "🔴"
    # limpo (e a UG não passa o limiar isolada) → None
    assert red_flag_tac("44444444000144", db_path=db, com_ug=False) is None


def test_red_flag_tac_db_ausente_degrada(tmp_path):
    # DB inexistente → não quebra, retorna None
    assert red_flag_tac("33333333000133", db_path=tmp_path / "nao_existe.db") is None
