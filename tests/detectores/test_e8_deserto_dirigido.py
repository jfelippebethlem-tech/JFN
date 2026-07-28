# -*- coding: utf-8 -*-
"""Rede de proteção do detector E8 — deserto/fracassado reincidente convertido em direta.

O padrão: publica-se um edital que ninguém consegue atender, ele dá deserto, repete-se, e ao fim
contrata-se diretamente com amparo no art. 75, III. O detector mede reincidência × desfecho.

A exculpatória é decisiva e está bem construída: se o órgão FLEXIBILIZOU o edital entre as
tentativas e ainda assim não houve interessados, isso é diligência somada a mercado raso — o
detector rebaixa, e no piso descarta. Sem esse guard, puniríamos justamente quem tentou.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.e8_deserto_dirigido import E8DesertoDirigido, _eh_falha

_P = {"processo": "SEI-TESTE/000012/2026"}


def _serie(*situacoes: str) -> list[dict]:
    return [{"situacao": s} for s in situacoes]


@pytest.mark.parametrize("s", ["deserta", "Deserto", "FRACASSADA", "fracassado por desclassificação"])
def test_reconhece_situacao_de_falha(s):
    assert _eh_falha(s) is True


@pytest.mark.parametrize("s", ["homologada", "adjudicada", "em andamento", "", None])
def test_situacao_normal_nao_e_falha(s):
    assert _eh_falha(s) is False


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_serie_ausente_e_nao_avaliavel():
    res = E8DesertoDirigido().avaliar({**_P})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "INDISPONÍVEL ≠ 0" in res.motivo_refutacao


def test_serie_sem_campo_situacao_e_nao_avaliavel():
    """Ter a lista de certames mas não saber o desfecho de nenhum não permite juízo."""
    res = E8DesertoDirigido().avaliar({**_P, "serie": [{"id": "1"}, {"id": "2"}]})
    assert res.status == "nao_avaliavel"
    assert res.valores["n_serie"] == 2


def test_serie_sem_desertos_e_descartada():
    res = E8DesertoDirigido().avaliar({**_P, "serie": _serie("homologada", "adjudicada")})
    assert res.status == "descartado"
    assert res.score == 0.0
    assert res.explicacao_inocente


# ───────────────────────────── régua reincidência × desfecho ──────────────────────────────────

def test_um_deserto_isolado_sem_conversao_nao_pontua():
    """Mercado raso explica um deserto. Acusar aqui seria transformar azar em indício."""
    res = E8DesertoDirigido().avaliar({**_P, "serie": _serie("deserta", "homologada")})
    assert res.status == "descartado"
    assert res.score == 0.0
    assert "mercado raso" in res.motivo_refutacao


def test_dois_desertos_sem_conversao_e_medio():
    res = E8DesertoDirigido().avaliar({**_P, "serie": _serie("deserta", "fracassada")})
    assert res.score == pytest.approx(ANCORAS["medio"])


def test_um_deserto_convertido_em_direta_e_forte():
    res = E8DesertoDirigido().avaliar({**_P, "serie": _serie("deserta"),
                                       "desfecho": {"tipo": "dispensa", "amparo": "art. 75 III"}})
    assert res.score >= ANCORAS["forte"]


@pytest.mark.parametrize("tipo", ["dispensa", "contratacao_direta", "inexigibilidade"])
def test_dois_desertos_convertidos_em_direta_e_critico(tipo):
    res = E8DesertoDirigido().avaliar({**_P, "serie": _serie("deserta", "fracassada"),
                                       "desfecho": {"tipo": tipo}})
    assert res.score >= ANCORAS["critico"] or res.score == pytest.approx(1.0)
    assert res.valores["n_desertos_fracassados"] == 2


def test_desfecho_competitivo_nao_agrava():
    res = E8DesertoDirigido().avaliar({**_P, "serie": _serie("deserta", "fracassada"),
                                       "desfecho": {"tipo": "pregao"}})
    assert res.score == pytest.approx(ANCORAS["medio"])


# ───────────────────────────── a exculpatória do ajuste ───────────────────────────────────────

def test_ajuste_entre_certames_rebaixa_um_grau():
    """O órgão flexibilizou o edital e mesmo assim ninguém veio — isso é diligência."""
    sem = E8DesertoDirigido().avaliar({**_P, "serie": _serie("deserta", "fracassada"),
                                       "desfecho": {"tipo": "dispensa"}})
    com = E8DesertoDirigido().avaliar({**_P, "serie": _serie("deserta", "fracassada"),
                                       "desfecho": {"tipo": "dispensa"},
                                       "ajuste_entre_certames": True})
    assert com.score < sem.score
    assert com.score == pytest.approx(ANCORAS["forte"])


def test_ajuste_no_piso_descarta_o_achado():
    """Rebaixar 'medio' com ajuste chega em 'fraco', e nesse ponto o detector descarta em vez de
    manter um indício frágil contra quem tentou."""
    res = E8DesertoDirigido().avaliar({**_P, "serie": _serie("deserta", "fracassada"),
                                       "ajuste_entre_certames": True})
    assert res.status == "descartado"
    assert res.score == 0.0
    assert "diligente" in res.motivo_refutacao


def test_valores_registram_as_situacoes_para_conferencia():
    res = E8DesertoDirigido().avaliar({**_P, "serie": _serie("deserta", "fracassada", "homologada"),
                                       "desfecho": {"tipo": "dispensa", "amparo": "art. 75 III"}})
    assert res.valores["situacoes"] == ["deserta", "fracassada", "homologada"]
    assert res.valores["amparo_desfecho"] == "art. 75 III"


def test_schema_de_saida_conforme_spec():
    d = E8DesertoDirigido().avaliar({**_P, "serie": _serie("deserta", "fracassada"),
                                     "desfecho": {"tipo": "dispensa"}}).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "E8"
    assert d["status"] in STATUS_VALIDOS
