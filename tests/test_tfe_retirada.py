# -*- coding: utf-8 -*-
"""Despublicação de OB é FATO, não ruído de dado.

`tfe_ob.ingest` apaga o exercício inteiro e reinsere a partir do zip — fielmente, e em silêncio.
Medido em 2026-08-04 contra o backup off-box de 02/08: **140 OBs de sete exercícios, somando
R$ 30.001.367,60, deixaram de ser publicadas pelo TFE-RJ** e sumiram da base sem que nada
avisasse. A descoberta veio dois dias depois, por um golden de números que quebrou, e só foi
possível porque havia backup para provar o que existia antes.
"""
import sqlite3

import pytest

from compliance_agent.collectors import tfe_ob


def _base(tmp_path, linhas):
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE ordens_bancarias (
        numero_ob TEXT, data_emissao TEXT, data_pagamento TEXT, ug_codigo TEXT, ug_nome TEXT,
        favorecido_cpf TEXT, favorecido_nome TEXT, valor REAL, tipo_ob TEXT, observacao TEXT,
        categoria TEXT, exercicio TEXT, coletado_em TEXT)""")
    con.executemany(
        "INSERT INTO ordens_bancarias(numero_ob, ug_codigo, exercicio, data_pagamento, ug_nome,"
        " favorecido_cpf, favorecido_nome, valor, observacao, categoria, coletado_em)"
        " VALUES(?,?,?,?,?,?,?,?,?,'tfe_ob','2026-08-02')", linhas)
    con.commit()
    return con


def test_ob_que_a_fonte_deixou_de_publicar_fica_registrada(tmp_path):
    con = _base(tmp_path, [
        ("2023OB00455", "133100", "2023", "2023-07-13", "ITERJ", "31954621000138",
         "LOCTECH LOCACAO DE MAQUINAS LTDA", 138093.99, "locação"),
        ("2023OB00167", "133100", "2023", "2023-03-30", "ITERJ", "31954621000138",
         "LOCTECH LOCACAO DE MAQUINAS LTDA", 138093.99, "locação"),
    ])
    # a fonte agora publica só uma das duas
    n = tfe_ob._registrar_retiradas(con, 2023, {("2023OB00167", "133100")})
    assert n == 1
    r = con.execute("SELECT numero_ob, valor, favorecido_nome FROM ob_retirada").fetchall()
    assert r == [("2023OB00455", 138093.99, "LOCTECH LOCACAO DE MAQUINAS LTDA")]


def test_nada_a_registrar_quando_a_fonte_mantem_tudo(tmp_path):
    con = _base(tmp_path, [("2023OB00167", "133100", "2023", "2023-03-30", "ITERJ", "x", "y", 1.0, "")])
    assert tfe_ob._registrar_retiradas(con, 2023, {("2023OB00167", "133100")}) == 0
    assert con.execute("SELECT COUNT(*) FROM ob_retirada").fetchone()[0] == 0


def test_registro_e_idempotente_e_nao_duplica(tmp_path):
    con = _base(tmp_path, [("2023OB00455", "133100", "2023", "2023-07-13", "ITERJ", "x", "y", 9.0, "")])
    tfe_ob._registrar_retiradas(con, 2023, set())
    tfe_ob._registrar_retiradas(con, 2023, set())
    assert con.execute("SELECT COUNT(*) FROM ob_retirada").fetchone()[0] == 1


def test_espaco_em_branco_no_numero_nao_inventa_retirada(tmp_path):
    """O CSV do TFE traz campos com espaço; comparar sem `strip` acusaria retirada inexistente."""
    con = _base(tmp_path, [(" 2023OB00167 ", " 133100 ", "2023", "2023-03-30", "ITERJ", "x", "y", 1.0, "")])
    assert tfe_ob._registrar_retiradas(con, 2023, {("2023OB00167", "133100")}) == 0


@pytest.mark.parametrize("ano_outro", ["2022", "2024"])
def test_so_olha_o_exercicio_que_esta_sendo_reingerido(tmp_path, ano_outro):
    """`ingest` reinsere UM ano; OB de outro exercício não some por não estar neste zip."""
    con = _base(tmp_path, [("2022OB00001", "133100", ano_outro, "2022-01-05", "ITERJ", "x", "y", 5.0, "")])
    assert tfe_ob._registrar_retiradas(con, 2023, set()) == 0
