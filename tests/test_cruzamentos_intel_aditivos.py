# -*- coding: utf-8 -*-
"""aditivos_estouro (cruzamentos_intel) — pct sobre o ACRÉSCIMO REAL (contrato_aditivo qualif='1') quando
existe; sem ele, vg−vi (inclui reajuste) vira indício NÃO confirmado (acrescimo_confirmado=False), rebaixado
na ordenação — nunca removido (honestidade)."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.cruzamentos_intel import aditivos_estouro


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE pcrj_contratos (
        numero_controle_pncp TEXT, fornecedor_nome TEXT, fornecedor_documento TEXT, orgao_nome TEXT,
        unidade TEXT, objeto TEXT, valor_inicial REAL, valor_global REAL, num_aditivos INTEGER,
        vigencia_fim TEXT);
    CREATE TABLE contrato_aditivo (
        numero_controle_pncp TEXT, qualif_acrescimo TEXT, valor_acrescido REAL);
    """)
    ins = ("INSERT INTO pcrj_contratos VALUES (?,?,?,?,?,?,?,?,?,?)")
    con.executemany(ins, [
        # K1: vg−vi=+40% MAS acréscimo real (qualif='1') = 10% → reajuste explica; NÃO é achado
        ("K1", "ALFA", "11111111000111", "SMS", "SMS", "serviço de limpeza", 100000.0, 140000.0, 1, "2025-12-31"),
        # K2: acréscimo real = 30% → estouro CONFIRMADO
        ("K2", "BETA", "22222222000122", "SMS", "SMS", "serviço de manutenção", 100000.0, 140000.0, 1, "2025-12-31"),
        # K3: sem contrato_aditivo → vg−vi=+50% vira indício NÃO confirmado (rebaixado, não removido)
        ("K3", "GAMA", "33333333000133", "SME", "SME", "fornecimento de merenda", 100000.0, 150000.0, 1, "2025-12-31"),
    ])
    con.executemany("INSERT INTO contrato_aditivo VALUES (?,?,?)", [
        ("K1", "1", 10000.0),
        ("K1", "2", 30000.0),   # qualif≠'1' (reajuste) não entra no acréscimo real
        ("K2", "1", 30000.0),
    ])
    con.commit()
    con.close()
    return p


def test_pct_sobre_acrescimo_real_exclui_reajuste(db):
    d = aditivos_estouro(db_path=db)
    assert d["ok"]
    contratos = {a["contrato"] for a in d["achados"]}
    assert "K1" not in contratos  # acréscimo real 10% < 25% — o +40% era reajuste
    k2 = next(a for a in d["achados"] if a["contrato"] == "K2")
    assert k2["pct"] == pytest.approx(30.0)
    assert k2["acrescimo_confirmado"] is True
    assert k2["estoura_teto"] is True


def test_sem_acrescimo_real_marca_nao_confirmado_e_rebaixa(db):
    d = aditivos_estouro(db_path=db)
    k3 = next(a for a in d["achados"] if a["contrato"] == "K3")
    assert k3["acrescimo_confirmado"] is False
    assert k3["pct"] == pytest.approx(50.0)  # vg−vi, sem confirmação granular
    # ordenação: K2 (confirmado, 30%) vem ANTES de K3 (não confirmado, 50%)
    ordem = [a["contrato"] for a in d["achados"]]
    assert ordem.index("K2") < ordem.index("K3")
