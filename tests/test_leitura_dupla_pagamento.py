# -*- coding: utf-8 -*-
"""Quem recebeu não se adivinha do texto — lê-se na Ordem Bancária.

MEDIDO contra `ordens_bancarias`, em 36 processos com OB vinculada: extrair o favorecido do texto
por regex acerta **36%** (13/36). A variante por vizinhança ganha um caso — 39%, ruído. E o TETO de
QUALQUER régua de texto é **58%**: em 42% dos processos o CNPJ de quem recebeu não está escrito ali.
Não é régua estreita, é fonte errada — e a regra nº 2 da casa já dizia onde está a verdade.

Isso só ficou possível porque a junção por `numero_sei` foi consertada na mesma sessão (achava OB em
0,2% do acervo, agora 62%). O confronto muda de natureza para melhor: em vez de duas leituras do
mesmo texto, é o que o processo DIZ contra o que foi PAGO.

E a conferência é por PERTINÊNCIA AO CONJUNTO, não contra o maior: um processo do acervo paga 1.199
favorecidos (repasse do PNAE às escolas). Ali "o favorecido" não tem resposta única, e cobrar o
maior fabricaria briga onde a IA acertou um dos legítimos.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import tools.sei_leitura_dupla as M

PROC = "030001/010747/2026"


@pytest.fixture
def pago():
    p = M.pagamento_do_processo(PROC)
    if not p.get("tem_ob"):
        pytest.skip("processo sem OB vinculada nesta base")
    return p


def _estado(campo, resposta):
    with patch.object(M, "texto_do_processo", lambda *a, **k: "Repasse do PNAE."):
        r = M.confrontar(PROC, gerar=lambda *a, **k: json.dumps({campo: resposta}))
    for balde in ("acordo", "discordancia", "ausencia_concorde"):
        if campo in r[balde]:
            return r[balde][campo]["estado"]
    return "?"


def test_acertar_UM_dos_favorecidos_e_acordo(pago):
    assert _estado("favorecido", sorted(pago["favorecidos"])[0]) == "acordo"


def test_apontar_o_orgao_em_vez_de_quem_recebeu_continua_briga(pago):
    """`42498659000160` é a SEEDUC — o órgão, que aparece no cabeçalho e não recebe."""
    assert "42498659000160" not in pago["favorecidos"]
    assert _estado("favorecido", "42498659000160") == "discordam"


def test_o_pagamento_declara_quantos_receberam(pago):
    assert pago["n_favorecidos"] > 1 and pago["n_obs"] > 1, (
        "sem declarar a pluralidade, 'o favorecido' vira resposta única e falsa")
