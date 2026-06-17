# -*- coding: utf-8 -*-
"""LIFECYCLE do processo SEI (regra do dono: 'não pode errar' — nunca pular o que ainda corre).

Cobre a captura da SITUAÇÃO AUTORITATIVA (read-time, na ficha) e o GATE FIRME de skip:
  • `_norm_situacao` — normaliza o sinal autoritativo p/ {arquivado, concluido, em andamento, ''}.
  • `_filho_vigente` — safeguard pai-com-filho-vigente (cadeia com aditivo/prorrogação => vivo).
  • `_lifecycle` — só marca `encerrado=True` com situação autoritativa arquivado/concluído E sem OB
    recente E sem aditivo próprio E sem filho vigente. Tudo o mais → encerrado=False (conservador).
  • `arvores_encerradas` — lê o gate firme da tabela sei_arvore (consumido só na fase update-diário).

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_sei_lifecycle.py -q
"""
from __future__ import annotations

import datetime as dt
import sqlite3

import pytest

from tools import sei_arvore_build as ab


def _ob(dias_atras: int) -> dict:
    return {"data_pagamento": (dt.date.today() - dt.timedelta(days=dias_atras)).isoformat(),
            "valor": 1000.0, "favorecido_cpf": "12345678000190", "favorecido_nome": "FORNEC X"}


# ───────────────────────── _norm_situacao ─────────────────────────
@pytest.mark.parametrize("entrada,esperado", [
    ("Arquivado", "arquivado"),
    ("processo arquivado definitivamente", "arquivado"),
    ("Concluído", "concluido"),
    ("encerrado", "concluido"),
    ("Em Andamento", "em andamento"),
    ("em tramitação", "em andamento"),
    ("", ""),
    ("qualquer coisa solta", ""),   # não casa => '' (honesto, desconhecido)
])
def test_norm_situacao(entrada, esperado):
    assert ab._norm_situacao(entrada) == esperado


# ───────────────────────── _filho_vigente (safeguard) ─────────────────────────
def test_filho_vigente_detecta_aditivo_na_cadeia():
    rec = {"cadeia": [{"titulo_rel": "Contrato", "texto": "celebrado TERMO ADITIVO de prazo"}]}
    assert ab._filho_vigente(rec) is True


def test_filho_vigente_falso_sem_marcador():
    rec = {"cadeia": [{"titulo_rel": "Empenho", "texto": "nota de empenho ordinária"}]}
    assert ab._filho_vigente(rec) is False


def test_filho_vigente_falso_sem_cadeia():
    assert ab._filho_vigente({}) is False


# ───────────────────────── _lifecycle: GATE FIRME de encerrado ─────────────────────────
def test_encerrado_so_com_situacao_autoritativa_e_corroboracao():
    ficha = {"objeto": "obra X", "situacao": "arquivado"}
    lifecycle, ultima, situacao, encerrado = ab._lifecycle(ficha, [], {})
    assert situacao == "arquivado"
    assert encerrado is True
    assert lifecycle == "encerrado_indicio"


def test_nao_encerra_com_ob_recente():
    ficha = {"objeto": "obra X", "situacao": "arquivado"}
    _, _, situacao, encerrado = ab._lifecycle(ficha, [_ob(30)], {})
    assert situacao == "arquivado"
    assert encerrado is False  # OB recente derruba o gate (pode haver execução em curso)


def test_nao_encerra_com_aditivo_proprio():
    ficha = {"objeto": "obra X", "situacao": "concluido",
             "analise": "houve termo aditivo de prazo recente"}
    _, _, _, encerrado = ab._lifecycle(ficha, [], {})
    assert encerrado is False


def test_nao_encerra_com_filho_vigente():
    ficha = {"objeto": "obra X", "situacao": "arquivado"}
    rec = {"cadeia": [{"texto": "contrato com PRORROGAÇÃO vigente"}]}
    _, _, _, encerrado = ab._lifecycle(ficha, [], rec)
    assert encerrado is False  # safeguard pai-com-filho-vigente


def test_nao_encerra_sem_sinal_autoritativo_mesmo_com_marcador_texto():
    # marcador de fecho no texto, mas situação NÃO declarada → indício, NUNCA gate firme
    ficha = {"objeto": "obra X", "resumo": "consta termo de encerramento do processo"}
    lifecycle, _, situacao, encerrado = ab._lifecycle(ficha, [], {})
    assert situacao == ""
    assert lifecycle == "encerrado_indicio"
    assert encerrado is False


def test_situacao_em_andamento_marca_ativo():
    ficha = {"objeto": "obra X", "situacao": "em andamento"}
    lifecycle, _, situacao, encerrado = ab._lifecycle(ficha, [], {})
    assert situacao == "em andamento"
    assert lifecycle == "ativo"
    assert encerrado is False


def test_ob_antiga_nao_impede_encerramento():
    ficha = {"objeto": "obra X", "situacao": "concluido"}
    _, ultima, _, encerrado = ab._lifecycle(ficha, [_ob(2000)], {})  # ~5,5 anos atrás
    assert encerrado is True
    assert ultima  # registrou a data da última OB


# ───────────────────────── arvores_encerradas (gate consumido pelo sweep diário) ─────────────────────────
def test_arvores_encerradas_le_gate(tmp_path):
    db = tmp_path / "t.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE sei_arvore (numero_sei TEXT PRIMARY KEY, encerrado INTEGER DEFAULT 0)")
    con.executemany("INSERT INTO sei_arvore (numero_sei, encerrado) VALUES (?,?)",
                    [("SEI-1/1/2020", 1), ("SEI-2/2/2024", 0), ("SEI-3/3/2019", 1)])
    con.commit(); con.close()
    assert ab.arvores_encerradas(db) == {"SEI-1/1/2020", "SEI-3/3/2019"}


def test_arvores_encerradas_db_inexistente_nao_pula_nada(tmp_path):
    assert ab.arvores_encerradas(tmp_path / "nao_existe.db") == set()


def test_arvores_encerradas_sem_coluna_nao_pula_nada(tmp_path):
    db = tmp_path / "velho.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE sei_arvore (numero_sei TEXT PRIMARY KEY)")  # base antiga sem `encerrado`
    con.commit(); con.close()
    assert ab.arvores_encerradas(db) == set()


# ───────────────────────── _digest_txt: regressão título vazio (IndexError) ─────────────────────────
def test_digest_txt_membro_cadeia_titulo_vazio_nao_crasha():
    """REGRESSÃO: membro da cadeia com título vazio fazia '' .splitlines()[0] estourar IndexError
    (quebrou o sei_arvore_build no run de 2026-06-17). Agora degrada p/ título vazio, sem crash."""
    ficha = {"objeto": "x", "documentos": []}
    rec = {"cadeia": [
        {"titulo_rel": "", "titulo": "", "texto": "SEI-330003/002534/2024 algo"},  # título vazio
        {"titulo_rel": None, "texto": ""},                                          # tudo None/vazio
    ]}
    txt, resumo = ab._digest_txt("SEI-1/2024", ficha, rec, [])
    assert "DOSSIÊ DE PROCESSO SEI" in txt
    assert resumo["n_membros"] == 2
