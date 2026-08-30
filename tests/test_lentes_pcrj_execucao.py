"""Lentes de execução orçamentária e controles de qualidade do dado (PCRJ).

O que se trava aqui, acima de tudo: **a borda da série não pode virar achado**. Uma base que
termina em 2023 mostra todo empenho de 2023 como "não pago" — é resto a pagar, quitado em 2024,
exercício que a base não tem.
"""
import sqlite3

import pytest

from tools import lentes_pcrj_execucao as E

DDL = """
CREATE TABLE pcrj_despesa (id INTEGER, exercicio INT, orgao TEXT, unidade TEXT,
  credor_documento TEXT, credor_nome TEXT, natureza TEXT, fonte_recurso TEXT,
  empenhado REAL, liquidado REAL, pago REAL, arquivo_origem TEXT, coletado_em TEXT)"""


@pytest.fixture()
def banco(tmp_path):
    def _criar(linhas):
        p = tmp_path / "e.db"
        con = sqlite3.connect(p)
        con.execute(DDL)
        con.executemany("INSERT INTO pcrj_despesa (exercicio,orgao,credor_documento,credor_nome,"
                        "natureza,empenhado,liquidado,pago) VALUES (?,?,?,?,?,?,?,?)", linhas)
        con.commit()
        con.close()
        return str(p)
    return _criar


def _l(ano, cnpj, nome, emp, liq, pago, orgao="SME", nat="33903901"):
    return (ano, orgao, cnpj, nome, nat, emp, liq, pago)


# ── a borda da série ─────────────────────────────────────────────────────────────────────────

def test_empenho_nao_pago_no_ultimo_ano_e_borda_nao_achado(banco):
    """Medido no acervo real: 430 dos 460 casos caíam no último exercício. É resto a pagar."""
    db = banco([_l(2022, "1" * 14, "ANTIGO", 5_000_000.0, 0, 0),
                _l(2023, "2" * 14, "BORDA", 9_000_000.0, 0, 0)])
    r = E.empenhado_sem_pagamento(db)
    assert [a["credor"] for a in r["achados"]] == ["ANTIGO"]
    assert [a["credor"] for a in r["na_borda_da_serie"]] == ["BORDA"]
    assert r["massa"] == pytest.approx(5_000_000.0), "a massa só soma exercício encerrado"


def test_borda_fica_visivel_e_nao_e_descartada(banco):
    db = banco([_l(2023, "2" * 14, "BORDA", 9_000_000.0, 0, 0)])
    r = E.empenhado_sem_pagamento(db)
    assert r["n"] == 0 and len(r["na_borda_da_serie"]) == 1


def test_superempenho_tambem_corta_a_borda(banco):
    db = banco([_l(2021, "1" * 14, "ANTIGO", 10_000_000.0, 2_000_000.0, 2_000_000.0),
                _l(2023, "2" * 14, "BORDA", 10_000_000.0, 1_000_000.0, 1_000_000.0)])
    r = E.superempenho(db)
    assert [a["credor"] for a in r["achados"]] == ["ANTIGO"]
    assert len(r["na_borda_da_serie"]) == 1


def test_exercicio_unico_corta_as_DUAS_bordas(banco):
    """Quem aparece só no primeiro ano pode ter começado antes; no último, continuado depois."""
    db = banco([_l(2019, "1" * 14, "PRIMEIRO ANO", 20e6, 20e6, 20e6),
                _l(2021, "2" * 14, "MIOLO", 20e6, 20e6, 20e6),
                _l(2023, "3" * 14, "ULTIMO ANO", 20e6, 20e6, 20e6)])
    r = E.fornecedor_de_exercicio_unico(db)
    assert [a["nome"] for a in r["achados"]] == ["MIOLO"]
    assert {a["nome"] for a in r["na_borda_da_serie"]} == {"PRIMEIRO ANO", "ULTIMO ANO"}


# ── empenhado × liquidado: o atesto muda a gravidade ────────────────────────────────────────

def test_atesto_separa_o_caso_grave(banco):
    """Liquidado é o reconhecimento de que o credor cumpriu (art. 63 da Lei 4.320/64)."""
    db = banco([_l(2021, "1" * 14, "COM ATESTO", 5e6, 5e6, 0),
                _l(2021, "2" * 14, "SEM ATESTO", 5e6, 0, 0),
                _l(2022, "3" * 14, "OUTRO", 1.0, 1.0, 1.0)])
    r = E.empenhado_sem_pagamento(db)
    assert r["n_com_atesto"] == 1
    assert next(a for a in r["achados"] if a["credor"] == "COM ATESTO")["houve_atesto"] is True


def test_superempenho_ignora_quem_nao_pagou_nada(banco):
    """Pagar zero é a outra lente, com natureza distinta — não pode contar duas vezes."""
    db = banco([_l(2021, "1" * 14, "ZERO", 5e6, 0, 0),
                _l(2022, "2" * 14, "X", 1.0, 1.0, 1.0)])
    assert E.superempenho(db)["n"] == 0


# ── CONTROLE: cascata ────────────────────────────────────────────────────────────────────────

def test_cascata_coerente_espera_zero(banco):
    db = banco([_l(2021, "1" * 14, "OK", 100.0, 80.0, 50.0)])
    r = E.cascata_coerente(db)
    assert r["n"] == 0 and r["prevalencia"] == 0.0


def test_cascata_detecta_liquidado_acima_do_empenhado(banco):
    db = banco([_l(2021, "1" * 14, "RUIM", 100.0, 150.0, 50.0)])
    r = E.cascata_coerente(db)
    assert r["liquidado_acima_do_empenhado"] == 1 and r["n"] >= 1


def test_cascata_detecta_pago_acima_do_liquidado(banco):
    db = banco([_l(2021, "1" * 14, "RUIM", 100.0, 50.0, 80.0)])
    assert E.cascata_coerente(db)["pago_acima_do_liquidado"] == 1


def test_cascata_detecta_valor_negativo(banco):
    db = banco([_l(2021, "1" * 14, "RUIM", -100.0, 0.0, 0.0)])
    assert E.cascata_coerente(db)["valores_negativos"] == 1


# ── CONTROLE: qualidade cadastral ───────────────────────────────────────────────────────────

def test_dv_de_cnpj_e_cpf():
    assert E._dv_cnpj_ok("11222333000181")          # CNPJ válido conhecido
    assert not E._dv_cnpj_ok("11222333000180")
    assert not E._dv_cnpj_ok("11111111111111"), "todos os dígitos iguais não é documento"
    assert E._dv_cpf_ok("52998224725")
    assert not E._dv_cpf_ok("52998224724")
    assert not E._dv_cpf_ok("11111111111")


def test_documento_mascarado_fica_fora_da_validacao_de_digito(banco):
    """Validar o que está oculto inventaria erro."""
    db = banco([_l(2021, "***201901**", "CHINA MEHECO CORPORATION", 100.0, 100.0, 100.0)])
    r = E.qualidade_cadastral(db)
    assert r["n_digito_verificador_invalido"] == 0
    assert r["documentos_mascarados_fora_do_teste"] == 1


def test_documento_com_razoes_divergentes(banco):
    db = banco([_l(2021, "***201901**", "CHINA MEHECO CORPORATION", 100.0, 100.0, 100.0),
                _l(2021, "***201901**", "GUINESS WORLD RECORDS LATAM LLC", 50.0, 50.0, 50.0)])
    r = E.qualidade_cadastral(db)
    assert r["documento_com_razoes_divergentes"] == 1
    assert r["achados"][0]["n_razoes"] == 2


def test_razao_de_pj_sob_documento_de_cpf(banco):
    db = banco([_l(2021, "52998224725", "ALFA COMERCIO LTDA", 100.0, 100.0, 100.0)])
    assert E.qualidade_cadastral(db)["n_pj_sob_documento_de_cpf"] == 1


def test_digito_invalido_e_detectado(banco):
    db = banco([_l(2021, "11222333000180", "EMPRESA COM CNPJ INVALIDO", 100.0, 100.0, 100.0)])
    r = E.qualidade_cadastral(db)
    assert r["n_digito_verificador_invalido"] == 1
    assert r["digito_verificador_invalido"][0]["tipo"] == "CNPJ"


def test_toda_lente_e_controle_declaram_o_contrato(banco):
    db = banco([_l(2021, "1" * 14, "X", 100.0, 100.0, 100.0)])
    for fn in E.LENTES + E.CONTROLES:
        r = fn(db)
        assert {"lente", "universo", "n", "prevalencia", "massa", "achados"} <= set(r), fn.__name__
        if r["universo"] == 0:
            assert r["prevalencia"] is None, f"{fn.__name__}: universo vazio virou 0%"
