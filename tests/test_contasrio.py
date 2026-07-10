# -*- coding: utf-8 -*-
"""Task 7 — carga de despesa por credor (Open_Data_Empenhos do Rio Transparente)."""
from pathlib import Path

from compliance_agent.emendas import db as edb
from compliance_agent.pcrj import contasrio, gastos_db

FIX = Path(__file__).parent / "fixtures" / "contasrio_empenhos_amostra.csv"


def test_carregar_empenhos_agrega_por_credor(tmp_path):
    con = edb.conectar(tmp_path / "t.db")
    gastos_db.init_schema(con)
    n = contasrio.carregar_empenhos_csv(con, FIX, arquivo_origem="Open_Data_Empenhos_2023.csv")
    assert n > 0
    tot = con.execute("select sum(empenhado), sum(liquidado), sum(pago) from pcrj_despesa").fetchone()
    assert tot[0] and tot[0] > 0
    # sanity agregado: empenhado >= liquidado >= pago (restos de exercícios
    # anteriores podem violar em arquivo cheio; na amostra 2023 deve valer)
    assert tot[0] >= tot[1] >= tot[2]
    ex = con.execute("select distinct exercicio from pcrj_despesa").fetchall()
    assert [r[0] for r in ex] == [2023]


def test_parse_linha_credor_vs_orgao():
    pj = {"Tipo de favorecido": "PESSOA JURIDICA", "Código do favorecido": "345678000199"}
    assert contasrio._e_credor_externo(pj) is True
    assert contasrio._normaliza_doc(pj) == "00345678000199"   # zfill(14)
    pf = {"Tipo de favorecido": "PESSOA FISICA", "Código do favorecido": "1234567890"}
    assert contasrio._normaliza_doc(pf).startswith("***")     # CPF mascarado
    org = {"Tipo de favorecido": "ORGAO", "Código do favorecido": "1000"}
    assert contasrio._e_credor_externo(org) is False


def test_carregar_contratos_csv(tmp_path):
    con = edb.conectar(tmp_path / "t.db")
    gastos_db.init_schema(con)
    fix = Path(__file__).parent / "fixtures" / "contasrio_contratos_amostra.csv"
    n = contasrio.carregar_contratos_csv(con, fix, arquivo_origem="Open_Data_Contratos_2022.csv")
    assert n > 0
    row = con.execute("""select numero_controle_pncp, fornecedor_documento, valor_inicial,
                         data_assinatura, fonte from pcrj_contratos limit 1""").fetchone()
    assert row["numero_controle_pncp"].startswith("contasrio:2022:")
    assert row["fonte"] == "contasrio"
    # data normalizada p/ ISO (detector D7 espera aaaa-mm-dd)
    assert row["data_assinatura"] is None or row["data_assinatura"][4] == "-"


def test_data_iso():
    assert contasrio._data_iso("28/04/2022") == "2022-04-28"
    assert contasrio._data_iso("") is None
