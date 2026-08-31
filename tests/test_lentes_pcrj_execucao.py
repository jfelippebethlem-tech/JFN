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


# ── agrupamento por RAIZ de CNPJ ─────────────────────────────────────────────────────────────

def test_troca_de_razao_social_nao_inventa_exercicio_unico(banco):
    """Medido: 0,96% das raízes têm mais de uma razão social. 'Companhia Brasileira de Soluções
    e Serviços' e 'ALELO S.A.' são o mesmo CNPJ; agrupar pelo NOME partiria a empresa em duas."""
    db = banco([_l(2020, "04740876000197", "COMPANHIA BRASILEIRA DE SOLUCOES", 10e6, 10e6, 10e6),
                _l(2021, "04740876000197", "ALELO S.A.", 10e6, 10e6, 10e6)])
    r = E.fornecedor_de_exercicio_unico(db, piso=1_000_000.0)
    assert r["n"] == 0, "é a mesma raiz em dois exercícios — não é exercício único"


def test_matriz_e_filial_sao_a_mesma_raiz(banco):
    """'Projeto Social Colibri' é a filial 0006 do 'Instituto Gnosis' 0001, não outra entidade."""
    db = banco([_l(2022, "10635117000103", "INSTITUTO GNOSIS", 10e6, 10e6, 10e6),
                _l(2023, "10635117000600", "PROJETO SOCIAL COLIBRI", 10e6, 10e6, 10e6)])
    assert E.fornecedor_de_exercicio_unico(db, piso=1_000_000.0)["n"] == 0


def test_documento_mascarado_sai_com_a_razao_declarada(banco):
    db = banco([_l(2021, "***201901**", "ESTRANGEIRA", 20e6, 20e6, 20e6)])
    r = E.fornecedor_de_exercicio_unico(db)
    assert r["n"] == 0 and r["linhas_fora_por_documento_mascarado"] == 1


def test_razoes_sociais_do_achado_sao_devolvidas(banco):
    db = banco([_l(2021, "1" * 14, "NOME A", 20e6, 20e6, 20e6),
                _l(2021, "1" * 14, "NOME B", 5e6, 5e6, 5e6),
                _l(2022, "2" * 14, "OUTRO", 1.0, 1.0, 1.0),
                _l(2019, "3" * 14, "BORDA", 1.0, 1.0, 1.0)])
    r = E.fornecedor_de_exercicio_unico(db)
    assert r["achados"][0]["razoes_sociais"] == ["NOME A", "NOME B"]


# ── pico de gasto por subelemento ────────────────────────────────────────────────────────────

def _sub(ano, sub, cnpj, pago):
    return (ano, "SME", cnpj, f"F{cnpj[:4]}", f"3390{sub}", pago, pago, pago)


def test_pico_exige_serie_para_ter_normal_contra_o_que_comparar(banco):
    """Com menos de 3 exercícios não há mediana que signifique alguma coisa."""
    db = banco([_sub(2021, "3004", "1" * 14, 50e6), _sub(2022, "3004", "1" * 14, 1e6)])
    assert E.pico_de_gasto_por_subelemento(db)["universo"] == 0


def test_pico_exige_volume_E_elenco_renovado(banco):
    """Só o volume marca 16,2% dos subelementos; é a combinação que discrimina."""
    # mercado A: volume explode E fornecedores novos
    linhas = [_sub(2019, "3004", "1" * 14, 1e6), _sub(2020, "3004", "1" * 14, 1e6),
              _sub(2021, "3004", "9" * 14, 50e6)]
    # mercado B: volume explode com OS MESMOS fornecedores
    linhas += [_sub(2019, "3007", "2" * 14, 1e6), _sub(2020, "3007", "2" * 14, 1e6),
               _sub(2021, "3007", "2" * 14, 50e6)]
    r = E.pico_de_gasto_por_subelemento(banco(linhas), piso=1_000_000.0)
    assert [a["subelemento"] for a in r["achados"]] == ["3004"]
    assert r["corte_amplo"]["n"] == 2, "o de elenco estável não some — fica no corte amplo"


def test_pico_devolve_a_serie_inteira(banco):
    linhas = [_sub(2019, "3004", "1" * 14, 1e6), _sub(2020, "3004", "1" * 14, 1e6),
              _sub(2021, "3004", "9" * 14, 50e6)]
    a = E.pico_de_gasto_por_subelemento(banco(linhas), piso=1_000_000.0)["achados"][0]
    assert set(a["serie"]) == {2019, 2020, 2021}
    assert a["ano_de_pico"] == 2021
    assert a["fracao_de_fornecedores_novos"] == pytest.approx(1.0)


def test_mercado_estavel_nao_e_marcado(banco):
    linhas = [_sub(ano, "3004", "1" * 14, 10e6) for ano in (2019, 2020, 2021, 2022)]
    assert E.pico_de_gasto_por_subelemento(banco(linhas), piso=1_000_000.0)["n"] == 0
