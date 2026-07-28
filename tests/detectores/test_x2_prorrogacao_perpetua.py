# -*- coding: utf-8 -*-
"""Rede de proteção do detector X2 — prorrogação perpétua sem teste de mercado.

Contrato que nunca volta ao mercado deixa de ser contrato e vira reserva. As réguas são de
tempo (>5 anos forte, >10 crítico) e de volume de prorrogações (≥3 sem nova licitação), com um
agravante próprio: a cadeia emergência → prorrogação → recontratação, que é como se mantém o
fornecedor sem certame parecendo regular.

Sem rede, sem banco.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.x2_prorrogacao_perpetua import X2ProrrogacaoPerpetua

_P = {"processo": "SEI-TESTE/000017/2026"}


def test_sem_tempo_e_sem_prorrogacoes_e_nao_avaliavel():
    res = X2ProrrogacaoPerpetua().avaliar({**_P})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_contrato_novo_nao_e_indicio():
    res = X2ProrrogacaoPerpetua().avaliar({**_P, "tempo_total_anos": 2.0})
    assert res.score == 0.0
    assert res.status == "descartado"


@pytest.mark.parametrize("anos,esperado", [
    (4.9, 0.0),
    (6.0, ANCORAS["forte"]),
    (11.0, ANCORAS["critico"]),
])
def test_regua_de_tempo_no_mesmo_objeto(anos, esperado):
    res = X2ProrrogacaoPerpetua().avaliar({**_P, "tempo_total_anos": anos})
    assert res.score == pytest.approx(esperado)


def test_tempo_calculado_pela_vigencia_quando_nao_vem_pronto():
    res = X2ProrrogacaoPerpetua().avaliar({**_P, "vigencia_inicio": "2014-01-01",
                                           "vigencia_fim_atual": "2026-01-01"})
    assert res.valores["tempo_total_anos"] is not None
    assert res.valores["tempo_total_anos"] > 10
    assert res.score >= ANCORAS["critico"] or res.score == pytest.approx(1.0)


@pytest.mark.parametrize("n,pontua", [(1, False), (2, False), (3, True), (7, True)])
def test_volume_de_prorrogacoes_sem_nova_licitacao(n, pontua):
    res = X2ProrrogacaoPerpetua().avaliar({**_P, "prorrogacoes": [{"n": i} for i in range(n)]})
    assert (res.score >= ANCORAS["forte"]) is pontua
    assert res.valores["n_prorrogacoes"] == n


def test_cadeia_emergencia_agrava_o_achado():
    """Emergência que vira prorrogação que vira recontratação mantém o fornecedor sem certame."""
    sem = X2ProrrogacaoPerpetua().avaliar({**_P, "tempo_total_anos": 6.0})
    com = X2ProrrogacaoPerpetua().avaliar({**_P, "tempo_total_anos": 6.0,
                                           "cadeia_emergencia": True})
    assert com.score > sem.score
    assert com.valores["cadeia_emergencia"] is True


def test_valores_declaram_a_fonte_do_tempo():
    """Peça de controle precisa dizer se o tempo veio da vigência ou de campo informado."""
    res = X2ProrrogacaoPerpetua().avaliar({**_P, "tempo_total_anos": 6.0})
    assert res.valores["fonte_tempo"]


def test_lixo_na_lista_de_prorrogacoes_nao_quebra():
    res = X2ProrrogacaoPerpetua().avaliar({**_P, "tempo_total_anos": 6.0,
                                           "prorrogacoes": [None, "texto", 42, {"n": 1}]})
    assert res.status in STATUS_VALIDOS
    assert res.valores["n_prorrogacoes"] == 1


def test_schema_de_saida_conforme_spec():
    d = X2ProrrogacaoPerpetua().avaliar({**_P, "tempo_total_anos": 11.0}).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "X2"
    assert d["status"] in STATUS_VALIDOS
