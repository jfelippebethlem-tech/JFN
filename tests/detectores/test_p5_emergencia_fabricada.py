# -*- coding: utf-8 -*-
"""Rede de proteção do detector P5 — emergência fabricada (art. 75, VIII, Lei 14.133/2021).

A tese é a do Acórdão 645/2007-Plenário do TCU: emergência que nasceu de falta de planejamento,
desídia ou má gestão NÃO autoriza dispensa. O detector mede isso por deltas temporais objetivos —
inércia (abriu a dispensa depois do vencimento que já conhecia), pré-escolha (proposta anterior à
abertura do processo) e recorrência (emergência virou rotina).

O contrapeso é forte e precisa ser respeitado: desastre real legitima a dispensa mesmo com preço
alto. Sem esse guard, o detector acusaria enchente e incêndio.

Sem rede, sem banco, sem LLM (as rubricas são injetadas por `_rubrica_*`).
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.p5_emergencia_fabricada import (
    P5EmergenciaFabricada,
    _delta_dias,
    _to_date,
)

_P = {"processo": "SEI-TESTE/000005/2026"}


# ───────────────────────────── parse e deltas ─────────────────────────────────────────────────

@pytest.mark.parametrize("valor", ["2026-03-10", "10/03/2026"])
def test_parse_de_data_aceita_iso_e_grafia_br(valor):
    d = _to_date(valor)
    assert d is not None and (d.year, d.month, d.day) == (2026, 3, 10)


def test_data_invalida_devolve_none_em_vez_de_chutar():
    assert _to_date("data que não existe") is None
    assert _to_date(None) is None


def test_delta_e_none_quando_falta_uma_das_pontas():
    from datetime import date
    assert _delta_dias(None, date(2026, 3, 10)) is None
    assert _delta_dias(date(2026, 3, 10), None) is None


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_sem_data_de_abertura_e_nao_avaliavel():
    res = P5EmergenciaFabricada().avaliar({**_P, "data_proposta": "2026-01-01"})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_emergencia_tempestiva_nao_inventa_indicio():
    """Dispensa aberta bem antes do vencimento, sem pré-escolha nem recorrência: nada a apontar."""
    res = P5EmergenciaFabricada().avaliar({**_P, "data_abertura_processo": "2026-01-10",
                                           "contrato_anterior": {"vencimento": "2026-06-30"}})
    assert res.status == "descartado"
    assert res.score == 0.0
    assert res.explicacao_inocente


# ───────────────────────────── inércia ────────────────────────────────────────────────────────

def test_dispensa_aberta_depois_do_vencimento_e_inercia_forte():
    """O órgão sabia a data do vencimento e deixou o serviço cair. É desídia, não emergência."""
    res = P5EmergenciaFabricada().avaliar({**_P, "data_abertura_processo": "2026-04-15",
                                           "contrato_anterior": {"vencimento": "2026-03-31"}})
    assert res.score >= ANCORAS["forte"]
    assert res.valores["delta_vencimento_abertura_dias"] == 15
    assert "APÓS o vencimento" in res.motivo_refutacao
    assert res.evidencia


def test_dispensa_as_vesperas_do_vencimento_e_inercia_media():
    res = P5EmergenciaFabricada().avaliar({**_P, "data_abertura_processo": "2026-03-20",
                                           "contrato_anterior": {"vencimento": "2026-03-31"}})
    assert res.score == pytest.approx(ANCORAS["medio"])
    assert res.valores["delta_vencimento_abertura_dias"] == -11


def test_planejamento_com_folga_nao_e_inercia():
    """Abrir 90 dias antes do vencimento é exatamente o que se espera de quem planeja."""
    res = P5EmergenciaFabricada().avaliar({**_P, "data_abertura_processo": "2026-01-01",
                                           "contrato_anterior": {"vencimento": "2026-03-31"}})
    assert res.score == 0.0


# ───────────────────────────── pré-escolha ────────────────────────────────────────────────────

def test_proposta_anterior_a_abertura_e_pre_escolha():
    """A proposta existir antes do processo significa que o fornecedor já estava definido."""
    res = P5EmergenciaFabricada().avaliar({**_P, "data_abertura_processo": "2026-04-10",
                                           "data_proposta": "2026-04-01"})
    assert res.score >= ANCORAS["forte"]
    assert res.valores["delta_proposta_abertura_dias"] == 9
    assert "pré-escolhido" in res.motivo_refutacao


def test_proposta_posterior_a_abertura_e_o_fluxo_normal():
    res = P5EmergenciaFabricada().avaliar({**_P, "data_abertura_processo": "2026-04-01",
                                           "data_proposta": "2026-04-10"})
    assert res.score == 0.0


# ───────────────────────────── recorrência ────────────────────────────────────────────────────

@pytest.mark.parametrize("n,pontua", [(0, False), (2, False), (3, True), (9, True)])
def test_recorrencia_de_emergencias_em_24_meses(n, pontua):
    """Emergência que se repete deixou de ser imprevisível — virou modo de operação."""
    res = P5EmergenciaFabricada().avaliar({**_P, "data_abertura_processo": "2026-04-01",
                                           "emergencias_orgao_24m": n})
    assert (res.score > 0) is pontua


def test_recorrencia_aceita_lista_alem_de_numero():
    res = P5EmergenciaFabricada().avaliar({**_P, "data_abertura_processo": "2026-04-01",
                                           "emergencias_orgao_24m": ["a", "b", "c", "d"]})
    assert res.valores["emergencias_orgao_24m"] == 4
    assert res.score >= ANCORAS["medio"]


# ───────────────────────────── exculpatórias estruturais ──────────────────────────────────────

def test_desastre_confirmado_rebaixa_o_achado():
    """Enchente e incêndio legitimam a dispensa. Sem este guard o detector acusa tragédia."""
    sem = P5EmergenciaFabricada().avaliar({**_P, "data_abertura_processo": "2026-04-15",
                                           "contrato_anterior": {"vencimento": "2026-03-31"}})
    com = P5EmergenciaFabricada().avaliar({**_P, "data_abertura_processo": "2026-04-15",
                                           "contrato_anterior": {"vencimento": "2026-03-31"},
                                           "desastre_confirmado": True})
    assert com.score < sem.score
    assert com.score <= ANCORAS["fraco"]
    assert "DESASTRE" in com.motivo_refutacao


def test_certame_anterior_fracassado_e_exculpatoria_parcial():
    """O órgão tentou licitar e o certame deu deserto — a inércia é parcialmente escusada.

    Parcialmente, e não totalmente: o fracasso pode ter sido induzido por edital restritivo,
    e o próprio texto do detector manda verificar isso.
    """
    sem = P5EmergenciaFabricada().avaliar({**_P, "data_abertura_processo": "2026-04-15",
                                           "contrato_anterior": {"vencimento": "2026-03-31"}})
    com = P5EmergenciaFabricada().avaliar({**_P, "data_abertura_processo": "2026-04-15",
                                           "contrato_anterior": {"vencimento": "2026-03-31"},
                                           "certame_anterior_fracassado": True})
    assert com.score < sem.score
    assert com.score <= ANCORAS["medio"]
    assert "induzido" in com.explicacao_inocente or "induzido" in com.motivo_refutacao


# ───────────────────────────── convergência ───────────────────────────────────────────────────

def test_inercia_e_pre_escolha_juntas_permanecem_no_teto_forte():
    """Duas regras objetivas batendo não podem estourar o teto da âncora — o score é [0,1]."""
    res = P5EmergenciaFabricada().avaliar({**_P, "data_abertura_processo": "2026-04-15",
                                           "contrato_anterior": {"vencimento": "2026-03-31"},
                                           "data_proposta": "2026-04-01",
                                           "emergencias_orgao_24m": 5})
    assert ANCORAS["forte"] <= res.score <= 1.0
    assert res.status == "confirmado"


# ───────────────────────────── schema §1.4 ────────────────────────────────────────────────────

def test_schema_de_saida_conforme_spec():
    res = P5EmergenciaFabricada().avaliar({**_P, "data_abertura_processo": "2026-04-15",
                                           "contrato_anterior": {"vencimento": "2026-03-31"}})
    d = res.to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "P5"
    assert d["status"] in STATUS_VALIDOS
    assert 0.0 <= d["score"] <= 1.0
