# -*- coding: utf-8 -*-
"""A perícia de execução tem de VER o pagamento do SIAFE, e achado de caso não entra na fila do sistema.

Medido em 29/10/2026: 550 dos 666 processos em que ela apontou 'ausência de Ordem Bancária' tinham OB
contabilizada no SIAFE (a OB não mora na pasta do SEI); e cada execução frágil virava 1 item em
`lex_feedback` — 2.400 dos 3.074 abertos.
"""
from __future__ import annotations

import inspect
import sqlite3

from tools import lex_execucao as L


def _base():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (processo TEXT, valor REAL, data_emissao TEXT, status TEXT)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?)", [
        ("SEI-330002/031566/24", 1000.0, "17/01/2025", "Contabilizado"),
        ("330002/31566/2024", 500.5, "03/12/2024", "Contabilizado"),
        ("SEI-330002/031566/2024", 9e9, "2024-05-01", "Anulado"),        # anulada não é pagamento
        ("SEI-330002/031567/2024", 7.0, "2024-05-01", "Contabilizado"),  # outro processo
    ])
    return con


def test_grafias_do_mesmo_processo_casam():
    assert L._chave_processo("SEI-330002/031566/24") == L._chave_processo("330002/31566/2024")
    assert L._chave_processo("350010/002351-8/2024") == "350010/2351/2024"
    assert L._chave_processo("0") is None


def test_mapa_soma_so_contabilizadas_do_processo():
    m = L.mapa_obs_siafe(_base(), ["SEI-330002/031566/2024"])
    d = m["330002/31566/2024"]
    assert d["n"] == 2 and abs(d["total"] - 1500.5) < 1e-6 and len(m) == 1


def test_bloco_do_prompt_diz_pago_ou_indisponivel():
    m = L.mapa_obs_siafe(_base(), ["SEI-330002/031566/2024"])
    b = L._bloco_siafe("SEI-330002/031566/2024", m)
    assert "2 OB(s) contabilizada(s), total R$ 1.500,50, emitidas de 03/12/2024 a 17/01/2025" in b
    assert "INDISPONÍVEL" in L._bloco_siafe("SEI-999999/000001/2024", m)


def test_prompt_leva_o_bloco_do_siafe():
    vistos = []

    def _gerar(prompt, sys_, t):
        vistos.append((prompt, sys_))
        raise TimeoutError
    m = L.mapa_obs_siafe(_base(), ["SEI-330002/031566/2024"])
    L.avaliar_processo(None, "SEI-330002/031566/2024", "obj", "", [], [], _gerar, m)
    assert "PAGAMENTO NO SIAFE (fonte oficial da OB): 2 OB(s)" in vistos[0][0]
    assert "NUNCA aponte 'ausência de OB'" in vistos[0][1]


def test_execucao_fragil_nao_vai_para_a_fila_do_sistema():
    assert "lex_feedback.registrar" not in inspect.getsource(L)


def test_vereditos_contestados_pelo_siafe_vem_primeiro():
    con = _base()
    con.execute("CREATE TABLE lex_execucao (numero_sei TEXT, indicios TEXT, resumo TEXT, nota_risco INT, em TEXT)")
    con.execute("CREATE TABLE sei_ficha (numero_sei TEXT, objeto TEXT, valores TEXT, documentos TEXT, "
                "red_flags TEXT, n_docs INT)")
    con.executemany("INSERT INTO lex_execucao VALUES (?,?,?,?,?)", [
        ("SEI-330002/031566/2024", '["Ausência de Ordem Bancária (OB)"]', "", 5, "2026-09-01T10:00"),
        ("SEI-111111/000001/2024", '["Ausência de Ordem Bancária (OB)"]', "", 5, "2026-09-01T10:00"),  # sem OB
    ])
    con.executemany("INSERT INTO sei_ficha VALUES (?,?,?,?,?,?)", [
        ("SEI-222222/000002/2024", "novo", "", "[]", "[]", 50),
        ("SEI-330002/031566/2024", "velho", "", "[]", "[]", 3),
        ("SEI-111111/000001/2024", "velho", "", "[]", "[]", 2),
    ])
    assert [a[0] for a in L._alvos(con, 2, False)] == ["SEI-330002/031566/2024", "SEI-222222/000002/2024"]


def test_so_quem_negou_a_ob_e_contestado():
    assert L._NEGA_OB.search("Ausência de Ordem Bancária (OB) para comprovar o pagamento")
    assert L._NEGA_OB.search("não há OB no trecho")
    assert not L._NEGA_OB.search("divergência de competência entre a ordem bancária de retenção e a liberação")
