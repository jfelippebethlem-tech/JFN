# -*- coding: utf-8 -*-
"""O mandato tem JANELA — e ignorá-la triplicou o número na primeira medição.

Pedido do dono (2026-08-05): candidatos de 2020/2022/2024 e anteriores × folha da Prefeitura de
2021 em diante (gestão Paes/Cavaliere), **apenas a folha da Prefeitura**.

Eleito em 2012 exerce de 2013 a 2016: folha de 2021 em diante não diz nada sobre aquele mandato.
Contar "presença na folha ≥2021" como sobreposição levou a análise a 23 chefes de executivo; com a
janela correta — jan/(ano+1) a dez/(ano+4) — são **8**. As outras duas separações que mudam o
sentido do número são o inativo (FUNPREVI/PREV*, que o art. 38 da CF não alcança) e a distinção
prefeito (art. 38, II — afastamento) × vereador (art. 38, III — compatibilidade de horários).
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.pcrj import candidato_x_folha as C


@pytest.fixture()
def base(tmp_path):
    p = tmp_path / "pcrj.db"
    con = sqlite3.connect(p)
    con.executescript("""
      CREATE TABLE tse_candidatura (nome_norm TEXT, nome_tse TEXT, ano INT, cargo TEXT,
                                    municipio TEXT, partido TEXT, eleito INT, outra_cidade INT);
      CREATE TABLE pcrj_folha_pref (nome_norm TEXT, nome TEXT, matricula TEXT, orgao TEXT,
                                    tipo_folha TEXT, competencia TEXT);
    """)
    con.commit()
    return p, con


def _cand(con, nome_norm, ano, cargo, eleito=1, outra=1):
    con.execute("INSERT INTO tse_candidatura VALUES (?,?,?,?,?,?,?,?)",
                (nome_norm, nome_norm.title(), ano, cargo, "MAGÉ", "PP", eleito, outra))


def _folha(con, nome_norm, comps, orgao="Comlurb", tipo="NORMAL", matricula="1"):
    for c in comps:
        con.execute("INSERT INTO pcrj_folha_pref VALUES (?,?,?,?,?,?)",
                    (nome_norm, nome_norm.title(), matricula, orgao, tipo, c))


def test_folha_fora_da_janela_do_mandato_nao_conta(base, monkeypatch):
    p, con = base
    _cand(con, "jose da silva", 2012, "VEREADOR")          # mandato 2013-2016
    _folha(con, "jose da silva", ["202106", "202112"])      # folha muito depois
    con.commit()
    monkeypatch.setattr(C._db, "conectar", lambda _p=None: sqlite3.connect(p))
    assert C.cruzar() == []


def test_folha_dentro_da_janela_conta(base, monkeypatch):
    p, con = base
    _cand(con, "maria souza", 2020, "PREFEITO")             # mandato 2021-2024
    _folha(con, "maria souza", ["202106", "202112", "202403"])
    con.commit()
    monkeypatch.setattr(C._db, "conectar", lambda _p=None: sqlite3.connect(p))
    r = C.cruzar()
    assert len(r) == 1 and r[0]["meses_no_mandato"] == 3
    assert C.resumo(r)["chefia_executivo"] == 1


def test_aposentado_do_funprevi_fica_de_fora(base, monkeypatch):
    """Art. 38 da CF trata do servidor em ATIVIDADE — inativo não acumula."""
    p, con = base
    _cand(con, "joao lima", 2020, "VEREADOR")
    _folha(con, "joao lima", ["202106"], orgao="Funprevi (Fundo de Previdência)", tipo="PREVNORMAL")
    con.commit()
    monkeypatch.setattr(C._db, "conectar", lambda _p=None: sqlite3.connect(p))
    assert C.cruzar() == []


def test_nome_com_mais_de_uma_matricula_e_descartado(base, monkeypatch):
    """Trava de prevalência: nome repetido na folha é homônimo provável."""
    p, con = base
    _cand(con, "ana costa", 2020, "VEREADOR")
    _folha(con, "ana costa", ["202106"], matricula="1")
    _folha(con, "ana costa", ["202106"], matricula="2")
    con.commit()
    monkeypatch.setattr(C._db, "conectar", lambda _p=None: sqlite3.connect(p))
    assert C.cruzar() == []
