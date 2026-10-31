# -*- coding: utf-8 -*-
"""A gravidade do fracionamento é o quanto se passou do LIMITE LEGAL, não quantos contratos são.

A fórmula anterior dava até +4 pela CONTAGEM e só +1 pelo excesso: com mediana de 8 contratos o
termo saturava e **451 de 451** alertas saíam com severidade alta — do rente ao teto ao 21×. Fila em
que tudo é urgente não prioriza nada.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.pcrj.pericia_gastos import _sev, d7_fracionamento

TETO = 65_492.11


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("""create table pcrj_contratos (numero_controle_pncp text, orgao_cnpj text,
                 orgao_nome text, fornecedor_documento text, fornecedor_nome text,
                 objeto text, valor_inicial real, valor_global real, data_assinatura text,
                 ano integer)""")
    return c


def _cenario(con, n, valor, forn="11111111000111"):
    for i in range(n):
        con.execute("insert into pcrj_contratos values (?,?,?,?,?,?,?,?,?,?)",
                    (f"C{forn[:4]}{i}", "99", "SMS", forn, "ALFA", "material",
                     valor, valor, f"2026-01-{(i % 28) + 1:02d}", 2026))
    con.commit()


def test_muitos_contratos_pequenos_NAO_e_o_mais_grave(con):
    """20 compras miúdas somando 1,3× o teto não podem pesar mais que 8 que somam 6×.

    Cada contrato tem de ficar ABAIXO do teto — é essa a hipótese do fracionamento (dispensa
    indevida), e a consulta do detector filtra por isso."""
    _cenario(con, 20, TETO * 1.3 / 20)                        # excesso 1,3x, 20 contratos miúdos
    _cenario(con, 8, TETO * 0.75, forn="22222222000122")      # excesso 6x, 8 contratos graúdos
    por = {x["evidencias"]["fornecedor"]: x["risco"] for x in d7_fracionamento(con)}
    assert len(por) == 2
    grande = por["22222222000122"]
    miudo = por["11111111000111"]
    assert grande > miudo, f"excesso de 6x ({grande}) tem de pesar mais que 1,3x ({miudo})"


def test_excesso_alto_chega_a_severidade_alta(con):
    _cenario(con, 12, TETO * 0.5)   # 12 x meio teto = 6x o limite, cada um abaixo dele
    a = d7_fracionamento(con)[0]
    assert a["risco"] >= 8 and _sev(a["risco"]) == "alta"


def test_rente_ao_teto_fica_em_media_por_mais_contratos_que_tenha(con):
    """O corte de 1,2× já existia e continua: nada some, só reordena."""
    _cenario(con, 30, TETO * 1.1 / 30)
    a = d7_fracionamento(con)[0]
    assert a["risco"] <= 7 and _sev(a["risco"]) != "alta"
