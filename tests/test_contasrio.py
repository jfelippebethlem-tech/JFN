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
