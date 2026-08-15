# -*- coding: utf-8 -*-
"""RELER PODE PIORAR — e sem histórico ninguém fica sabendo.

Medido em 2026-08-15 no `080002/000803/2025` (AMC, R$ 6,64 mi): completar o arquivo de 33 para 40
documentos fez a régua trocar o TAC de `158/2024` — o correto, citado no despacho de encaminhamento —
por `1840/2024`, que pertence à **ANDRÔMEDA**, processo `080002/016649/2024`, R$ 4.073,32. O
documento que entrou era o extrato do Diário Oficial da FSERJ publicando **27 TACs de uma vez**;
todos os candidatos ficaram com uma ocorrência cada e o "vencedor" saiu de desempate arbitrário.

Arquivo MAIOR, leitura PIOR — e nada disso vira erro: a cobertura segue 100%, o campo segue
preenchido, e o número trocado tem cara de achado.

`INSERT OR REPLACE` apagava a leitura anterior, que é a única testemunha da troca. Sem histórico, o
"reler e diferir" só funciona para quem lembrou de salvar o "antes" à mão ANTES de reler — ou seja,
nunca funciona para o que já passou.
"""
from __future__ import annotations

import json
import sqlite3

from tools.sei_leitura_dupla import _gravar


def _laudo(processo: str, tac: str, chars: int) -> dict:
    return {"processo": processo, "chars": chars, "truncado": True, "n_acordo": 1,
            "n_discordancia": 0, "n_ausencia": 0, "ausencia_concorde": [],
            "deterministico": {"tac": {"valor": tac, "ocorrencias": 1, "alternativas": []}},
            "ia": {"estado": "ok", "fatos": {}}, "discordancia": {}}


def test_releitura_guarda_a_leitura_anterior():
    con = sqlite3.connect(":memory:")
    _gravar(con, _laudo("080002/000803/2025", "158/2024", 100))
    _gravar(con, _laudo("080002/000803/2025", "1840/2024", 200))

    atual = con.execute("SELECT deterministico FROM sei_leitura_dupla").fetchall()
    assert len(atual) == 1, "a tabela corrente continua com uma linha por processo"
    assert json.loads(atual[0][0])["tac"]["valor"] == "1840/2024"

    hist = con.execute("SELECT chars, deterministico FROM sei_leitura_dupla_hist").fetchall()
    assert len(hist) == 1, "a leitura anterior tem de sobreviver à sobrescrita"
    assert hist[0][0] == 100
    assert json.loads(hist[0][1])["tac"]["valor"] == "158/2024", \
        "sem o valor ANTIGO no histórico, a troca do TAC é invisível"


def test_primeira_leitura_nao_inventa_historico():
    """Processo lido pela primeira vez não tem 'antes' — histórico vazio, não uma linha fantasma."""
    con = sqlite3.connect(":memory:")
    _gravar(con, _laudo("070002/019153/2024", "NAO_CONSTA", 150))
    assert con.execute("SELECT COUNT(*) FROM sei_leitura_dupla_hist").fetchone()[0] == 0
