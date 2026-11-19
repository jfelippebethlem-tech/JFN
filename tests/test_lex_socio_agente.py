# -*- coding: utf-8 -*-
"""Lex: sócio na folha pública vira achado estrutural graduado pelo ENTE — só com identidade conferida pelo CPF
(19/11/2026: par só-por-nome nunca vira achado)."""
from __future__ import annotations

from compliance_agent.lex_conflito import achado_socio_agente


def test_sem_socios_nao_ha_achado():
    assert achado_socio_agente([]) is None


def test_socio_da_propria_fserj_e_grave_4():
    a = achado_socio_agente([{"nome": "VANESSA TAVARES MANHAES", "cargo": "DIRETOR ASSISTENCIAL",
                              "vinculo": "CARGO COMISSAO", "orgao": "FUNDACAO SAUDE DO ESTADO DO RIO DE JANEIRO", "origem": "folha_estado"}])
    assert a["rf"] == "DD/SOCIO-AGENTE" and a["grav"] == 4
    assert "própria saúde estadual" in a["obs"] and "CPF conferido" in a["obs"]


def test_socio_da_ses_e_3_e_outro_orgao_e_2():
    ses = achado_socio_agente([{"nome": "TURIBIO COELHO LEAL FILHO", "cargo": "MÉDICO", "vinculo": "EFETIVO",
                                "orgao": "SECRETARIA DE ESTADO DE SAUDE", "origem": "folha_estado"}])
    assert ses["grav"] == 3
    pm = achado_socio_agente([{"nome": "MARCOS RIBEIRO", "cargo": "SUBTENENTE PM", "vinculo": "EFETIVO",
                               "orgao": "SECRETARIA DE ESTADO DE POLICIA MILITAR", "origem": "folha_estado"}])
    assert pm["grav"] == 2


def test_so_pelo_nome_nao_vira_achado():
    """Sócio sem CPF comparável (ALERJ, folha municipal, TJRJ) fica INDETERMINADO e não acende o Lex."""
    assert achado_socio_agente([{"nome": "MARCOS RIBEIRO", "cargo": "ASSESSOR", "vinculo": "ALERJ", "orgao": "ALERJ",
                                 "origem": "alerj", "selo": "INDETERMINADO"}]) is None


def test_identidade_socio_folha_pela_regua():
    import sqlite3
    from compliance_agent.lex_conflito import _identidade_socio_folha
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE registros_folha (nome TEXT, cpf TEXT, fonte TEXT, competencia TEXT)")
    con.executemany("INSERT INTO registros_folha VALUES (?,?,?,?)", [
        ("ANA PAULA SOBRAL", "XX123456XXX", "gesperj_estado", "2026-06"),     # janela 4–9
        ("RUI COSTA PRADO", "XX654321XXX", "gesperj_estado", "2026-06"),
        ("LIA TJ MOURA", None, "tjrj_anexo8", "2026-05")])
    r = _identidade_socio_folha(con, [("ANA PAULA SOBRAL", "***123456**"), ("RUI COSTA PRADO", "***111111**"),
                                      ("LIA TJ MOURA", "***123456**")])
    assert r[("ANA PAULA SOBRAL", "***123456**")][0] == "VERIFICADO"      # positivo
    assert r[("RUI COSTA PRADO", "***111111**")][0] == "HOMONIMO"         # negativo
    assert r[("LIA TJ MOURA", "***123456**")][0] == "INDETERMINADO"       # sem CPF na fonte
