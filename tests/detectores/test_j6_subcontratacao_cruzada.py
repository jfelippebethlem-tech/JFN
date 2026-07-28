# -*- coding: utf-8 -*-
"""Rede de proteção do detector J6 — subcontratação cruzada / consórcio anômalo.

Duas formas de repartir o butim sem parecer cartel:
· o vencedor SUBCONTRATA justamente quem "perdeu" o certame — a competição era encenação;
· duas empresas que se habilitariam SOZINHAS formam consórcio — em vez de competir, somam.

O cruzamento é por RAIZ de CNPJ (8 primeiros dígitos), não pelo CNPJ inteiro: filial e matriz
são a mesma empresa, e usar o número completo deixaria passar o caso mais óbvio.

Sem rede, sem banco.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.j6_subcontratacao_cruzada import J6SubcontratacaoCruzada

_P = {"processo": "SEI-TESTE/000022/2026"}

_VENCEDOR = "11222333000144"
_PERDEDOR = "44555666000177"
_TERCEIRO = "99000111000122"


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_sem_subcontratadas_e_sem_consorcio_e_nao_avaliavel():
    res = J6SubcontratacaoCruzada().avaliar({**_P, "licitantes": [_VENCEDOR, _PERDEDOR]})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_subcontratada_de_fora_do_certame_nao_pontua():
    res = J6SubcontratacaoCruzada().avaliar({
        **_P, "licitantes": [_VENCEDOR, _PERDEDOR],
        "subcontratadas": [{"cnpj": _TERCEIRO}]})
    assert res.score == 0.0
    assert res.status == "descartado"
    assert res.explicacao_inocente


# ───────────────────────────── subcontratação cruzada ─────────────────────────────────────────

def test_subcontratar_quem_perdeu_o_mesmo_certame_e_critico():
    """A competição era encenação: o 'perdedor' recebe sua parte por subcontratação."""
    res = J6SubcontratacaoCruzada().avaliar({
        **_P, "licitantes": [_VENCEDOR, _PERDEDOR],
        "subcontratadas": [{"cnpj": _PERDEDOR}]})
    assert res.score >= ANCORAS["critico"] or res.score == pytest.approx(1.0)
    assert res.valores["subcontratadas_que_disputaram"] == [_PERDEDOR]
    assert res.evidencia


def test_cruzamento_e_por_raiz_de_cnpj_nao_pelo_numero_inteiro():
    """Filial e matriz são a mesma empresa. Comparar o CNPJ completo deixaria passar o caso óbvio."""
    filial = _PERDEDOR[:8] + "000288"
    res = J6SubcontratacaoCruzada().avaliar({
        **_P, "licitantes": [_VENCEDOR, _PERDEDOR],
        "subcontratadas": [{"cnpj": filial}]})
    assert res.score >= ANCORAS["critico"] or res.score == pytest.approx(1.0)


def test_subcontratada_que_disputou_certame_ANALOGO_e_forte():
    """Repartição recorrente entre certames do mesmo órgão — forte, não crítico."""
    res = J6SubcontratacaoCruzada().avaliar({
        **_P, "licitantes": [_VENCEDOR],
        "subcontratadas": [{"cnpj": _PERDEDOR}],
        "certames_relacionados": [[_PERDEDOR, _TERCEIRO]]})
    assert res.score >= ANCORAS["forte"]
    assert res.valores["subcontratadas_em_certames_analogos"] == [_PERDEDOR]


def test_mesmo_certame_vence_o_analogo_na_gravidade():
    res = J6SubcontratacaoCruzada().avaliar({
        **_P, "licitantes": [_VENCEDOR, _PERDEDOR],
        "subcontratadas": [{"cnpj": _PERDEDOR}],
        "certames_relacionados": [[_PERDEDOR]]})
    assert res.valores["subcontratadas_que_disputaram"] == [_PERDEDOR]
    assert res.valores["subcontratadas_em_certames_analogos"] == []


# ───────────────────────────── consórcio anômalo ──────────────────────────────────────────────

def test_duas_consorciadas_autossuficientes_e_forte():
    """Quem se habilitaria sozinha não precisa de consórcio — precisa não competir."""
    res = J6SubcontratacaoCruzada().avaliar({
        **_P, "licitantes": [_VENCEDOR],
        "consorcio": [{"cnpj": _VENCEDOR, "atende_habilitacao_sozinha": True},
                      {"cnpj": _PERDEDOR, "atende_habilitacao_sozinha": True}]})
    assert res.score >= ANCORAS["forte"]
    assert len(res.valores["consorciadas_autossuficientes"]) == 2


def test_consorcio_com_uma_so_autossuficiente_nao_pontua():
    """Consórcio para somar capacidade que nenhuma tem sozinha é exatamente o instituto legal."""
    res = J6SubcontratacaoCruzada().avaliar({
        **_P, "licitantes": [_VENCEDOR],
        "consorcio": [{"cnpj": _VENCEDOR, "atende_habilitacao_sozinha": True},
                      {"cnpj": _PERDEDOR, "atende_habilitacao_sozinha": False}]})
    assert res.score == 0.0


def test_consorcio_sem_informacao_de_autossuficiencia_nao_chuta():
    """Sem saber se cada uma se habilitaria sozinha, não há juízo — e o detector não inventa."""
    res = J6SubcontratacaoCruzada().avaliar({
        **_P, "licitantes": [_VENCEDOR],
        "consorcio": [{"cnpj": _VENCEDOR}, {"cnpj": _PERDEDOR}]})
    assert res.valores["consorciadas_autossuficientes"] == []
    assert res.score == 0.0


# ───────────────────────────── robustez e schema ──────────────────────────────────────────────

def test_lixo_nas_listas_nao_quebra():
    res = J6SubcontratacaoCruzada().avaliar({
        **_P, "licitantes": [_VENCEDOR, _PERDEDOR],
        "subcontratadas": [{"cnpj": _PERDEDOR}, None, "texto", 42],
        "consorcio": [None, "x"]})
    assert res.status in STATUS_VALIDOS
    assert res.valores["n_subcontratadas"] == 1


def test_schema_de_saida_conforme_spec():
    d = J6SubcontratacaoCruzada().avaliar({
        **_P, "licitantes": [_VENCEDOR, _PERDEDOR],
        "subcontratadas": [{"cnpj": _PERDEDOR}]}).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "J6"
    assert d["status"] in STATUS_VALIDOS
