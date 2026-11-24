# -*- coding: utf-8 -*-
"""E10 `e10.p5_emergencia_recorrente` (O5.3 fatia 1): uma linha por PROCESSO (a soma por item inflava 2,3×), o
enquadramento legal como prova, só sobre processos elegíveis na E9. Fixtures sintéticas."""
import sqlite3

import pytest

from compliance_agent.aplicacao.detectores import emergencia_recorrente as P5


@pytest.fixture()
def fonte(tmp_path):
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE compras_diretas_tcerj(processo, unidade, ano_processo INTEGER, fornecedor, valor, objeto,"
                " enquadramento_legal)")
    con.commit()
    con.close()
    return p


def _inserir(p, linhas):
    con = sqlite3.connect(p)
    con.executemany("INSERT INTO compras_diretas_tcerj VALUES (?,?,?,?,?,?,?)", linhas)
    con.commit()
    con.close()
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def _anotar(itens, e9=None):
    for c in itens:
        c["e9"] = (e9 or {}).get(c["processo"], "E")
    return itens


def test_positivo_cinco_processos_emergenciais_viram_indicio(fonte):
    # o objeto não diz "emergencial": é o DISPOSITIVO (art. 75, VIII) que prova a emergência
    con = _inserir(fonte, [(f"SEI-{i}", "HOSPITAL X", 2025, "LOCALMED", 1000.0 * i, "PEITO DE FRANGO",
                            "Lei 14.133/2021, Art. 75, VIII") for i in range(1, 6)])
    ds = P5.detectar(_anotar(P5.carregar(con).itens))
    assert len(ds) == 1 and ds[0].estado == "INDICIO" and ds[0].grupo == "HOSPITAL X|2025"
    assert ds[0].valores["n"] == 5 and ds[0].valores["total"] == 15000.0
    assert ds[0].valores["concentracao_dominante"] == 1.0 and len(ds[0].evidencias) == 5


def test_negativo_itens_do_mesmo_processo_nao_somam(fonte):
    # UM processo com 6 itens (o `valor` repete o total em cada um): é UMA emergência, não seis
    con = _inserir(fonte, [("SEI-1", "DETRAN", 2025, "VIGILANCIA SA", 24800000.0, f"VIGILÂNCIA ITEM {i}",
                            "Art. 75, VIII") for i in range(6)])
    itens = P5.carregar(con).itens
    assert len(itens) == 1 and itens[0]["valor"] == 24800000.0
    assert P5.detectar(_anotar(itens)) == []


def test_negativo_processo_sem_elegibilidade_nao_conta(fonte):
    con = _inserir(fonte, [(f"SEI-{i}", "HOSPITAL X", 2025, "LOCALMED", 10.0, "X", "Art. 75, VIII")
                           for i in range(1, 6)])
    itens = _anotar(P5.carregar(con).itens, {"SEI-3": "?:SEM_CNPJ"})
    assert P5.detectar(itens) == []                     # 4 elegíveis < mínimo de 5
    r = P5.resumo(itens, [])
    assert r["emergenciais_indeterminadas"] == 1 and r["cobertura"] == 0.8


def test_dispositivo_de_outro_inciso_nao_vira_emergencia(fonte):
    con = _inserir(fonte, [(f"SEI-{i}", "SEC", 2025, "ACME", 10.0, "AQUISIÇÃO EMERGENCIAL", "Art. 75, II")
                           for i in range(1, 7)])
    assert P5.detectar(_anotar(P5.carregar(con).itens)) == []


def test_carregar_grupo_relê_so_o_grupo(fonte):
    con = _inserir(fonte, [("SEI-1", "A", 2025, "F", 1.0, "O", "Art. 75, VIII"),
                           ("SEI-2", "B", 2025, "F", 1.0, "O", "Art. 75, VIII")])
    assert [c["processo"] for c in P5.carregar_grupo(con, "B|2025").itens] == ["SEI-2"]
