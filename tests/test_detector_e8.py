# -*- coding: utf-8 -*-
"""Detector E8 — deserto/fracassado dirigido (edital inviável → dispensa art. 75 III).
Fecha a lacuna `deserto_fracassado_dirigido` do catálogo canônico.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detector_e8.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.base import ANCORAS
from compliance_agent.detectores.e8_deserto_dirigido import E8DesertoDirigido


def _valido(r):
    assert r.detector == "E8" and r.status in ("confirmado", "descartado", "nao_avaliavel")
    d = r.to_dict()
    assert 0.0 <= d["score"] <= 1.0


def _serie(*situacoes):
    return [{"situacao": s, "data": f"2026-0{i+1}-01"} for i, s in enumerate(situacoes)]


def test_dois_desertos_com_dispensa_e_critico():
    ctx = {"processo": "e8-1", "serie": _serie("deserta", "fracassada"),
           "desfecho": {"tipo": "dispensa", "amparo": "art. 75 III"}}
    r = E8DesertoDirigido().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado" and r.score == ANCORAS["critico"]
    assert "75" in r.motivo_refutacao


def test_um_deserto_com_dispensa_e_forte():
    ctx = {"processo": "e8-2", "serie": _serie("deserta", "homologada"),
           "desfecho": {"tipo": "contratacao_direta"}}
    r = E8DesertoDirigido().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado" and r.score == ANCORAS["forte"]


def test_reincidencia_sem_desfecho_e_medio():
    r = E8DesertoDirigido().avaliar({"processo": "e8-3", "serie": _serie("deserta", "deserta")})
    _valido(r)
    assert r.status == "confirmado" and r.score == ANCORAS["medio"]


def test_deserto_isolado_sem_dispensa_descarta():
    """Mercado raso é explicação inocente suficiente — 1 deserto sem conversão NÃO pontua."""
    r = E8DesertoDirigido().avaliar({"processo": "e8-4", "serie": _serie("deserta")})
    _valido(r)
    assert r.status == "descartado" and r.score == 0.0


def test_ajuste_entre_certames_exculpa_um_nivel():
    """Órgão que FLEXIBILIZOU o edital entre tentativas: critico→forte; medio→descartado."""
    ctx = {"processo": "e8-5", "serie": _serie("deserta", "deserta"),
           "desfecho": {"tipo": "dispensa"}, "ajuste_entre_certames": True}
    r = E8DesertoDirigido().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado" and r.score == ANCORAS["forte"]  # rebaixado de critico
    ctx2 = {"processo": "e8-6", "serie": _serie("deserta", "deserta"), "ajuste_entre_certames": True}
    r2 = E8DesertoDirigido().avaliar(ctx2)
    _valido(r2)
    assert r2.status == "descartado"  # medio→fraco→descarta (diligência + mercado raso)


def test_serie_sem_situacao_nao_avaliavel():
    r = E8DesertoDirigido().avaliar({"processo": "e8-7", "serie": [{"certame": "X"}]})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert "INDISPONÍVEL" in r.motivo_refutacao


def test_sem_falhas_descarta():
    r = E8DesertoDirigido().avaliar({"processo": "e8-8", "serie": _serie("homologada", "homologada")})
    _valido(r)
    assert r.status == "descartado"


def test_registrado_no_pipeline():
    from compliance_agent.detectores import REGISTRO
    assert "E8" in REGISTRO