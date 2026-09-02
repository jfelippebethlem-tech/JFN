# -*- coding: utf-8 -*-
"""O número da OB só é único DENTRO da UG — a chave da tabela canônica tem de dizer isso.

MEDIDO EM 2026-08-09, e é perda de dado, não teoria. `ob_orcamentaria_siafe` foi criada com
`PRIMARY KEY (numero_ob)` e a ingestão faz `INSERT OR REPLACE`. Mas o número da OB se repete entre
unidades: no espelho TFE, **133.295 de 198.894 números distintos (67%) aparecem em mais de uma UG**
— `2024OB00284` existe em **72 UGs**. Ou seja: cada coleta nova SOBRESCREVIA a linha homônima de
outra unidade, calada.

O rastro do estrago: o `siafe_sweep_full` registrou em 25/06 "180100 2023: 10046 ing | ok=True" com
19 fatias, e a tabela hoje tem **exatamente 1.000** linhas dessa UG/ano, todas com numeração
contígua (`2023OB27/28/29`) — a assinatura de UMA consulta capada, não das 19 fatias. A AMIL não
tem NENHUMA OB de 2019 a 2022. Foi assim que a PHOTONLUX entrou na fila do fiscal com R$ 4,3 mi
enquanto o espelho registra R$ 370,1 mi.

A casa já tinha a chave certa na tabela irmã: `collectors/tfe_ob.py` usa
`PRIMARY KEY (numero_ob, ug_codigo, exercicio)`. A tabela do SIAFE ficou para trás.
"""
from __future__ import annotations

import sqlite3

import pytest

import compliance_agent.siafe_ob_orcamentaria as M


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "c.db"
    monkeypatch.setattr(M, "_DB", p)
    return p


def _linha(numero: str, ug: str, valor: str = "1.000,00") -> list:
    fora = []
    for c in M._COLS_SIAFE:
        fora.append({"numero_ob": numero, "ug_emitente": ug, "valor": valor}.get(c, ""))
    return fora


def test_mesma_ob_em_ugs_diferentes_nao_se_apaga(db):
    M.ingerir(2023, [], [_linha("2023OB00284", "180100")])
    M.ingerir(2023, [], [_linha("2023OB00284", "294200")])
    con = sqlite3.connect(db)
    ugs = {r[0] for r in con.execute(
        "SELECT ug_emitente FROM ob_orcamentaria_siafe WHERE numero_ob='2023OB00284'")}
    assert ugs == {"180100", "294200"}, (
        f"a OB de uma UG apagou a da outra — ficou {ugs}; é a perda silenciosa de 67% dos números")


def test_reingestao_da_mesma_ob_atualiza_sem_duplicar(db):
    """SIAFE PREPONDERA continua valendo DENTRO da mesma (OB, UG, exercício)."""
    M.ingerir(2023, [], [_linha("2023OB00284", "180100", "1.000,00")])
    M.ingerir(2023, [], [_linha("2023OB00284", "180100", "2.500,00")])
    con = sqlite3.connect(db)
    linhas = con.execute(
        "SELECT valor FROM ob_orcamentaria_siafe WHERE numero_ob='2023OB00284'").fetchall()
    assert len(linhas) == 1 and linhas[0][0] == 2500.0


def test_mesma_ob_em_exercicios_diferentes_convive(db):
    M.ingerir(2023, [], [_linha("OB000001", "180100")])
    M.ingerir(2024, [], [_linha("OB000001", "180100")])
    con = sqlite3.connect(db)
    assert con.execute(
        "SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE numero_ob='OB000001'").fetchone()[0] == 2


def test_tabela_antiga_e_migrada_sem_perder_linha(db):
    """Base já existente com a PK velha: a migração preserva o que sobrou e destrava o resto."""
    con = sqlite3.connect(db)
    cols = ", ".join(f"{c} TEXT" for c in M._COLS_SIAFE if c != "valor")
    con.execute(f"CREATE TABLE ob_orcamentaria_siafe ({cols}, valor REAL, exercicio INTEGER, "
                "coletado_em TEXT, PRIMARY KEY (numero_ob))")
    con.execute("INSERT INTO ob_orcamentaria_siafe (numero_ob, ug_emitente, valor, exercicio) "
                "VALUES ('2023OB00284','180100',9.0,2023)")
    con.commit()
    con.close()

    M.ingerir(2023, [], [_linha("2023OB00284", "294200")])
    con = sqlite3.connect(db)
    ugs = {r[0] for r in con.execute(
        "SELECT ug_emitente FROM ob_orcamentaria_siafe WHERE numero_ob='2023OB00284'")}
    assert ugs == {"180100", "294200"}, "a migração não destravou a chave (ou perdeu a linha antiga)"
