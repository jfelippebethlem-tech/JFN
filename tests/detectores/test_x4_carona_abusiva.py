# -*- coding: utf-8 -*-
"""Rede de proteção do detector X4 — carona abusiva em ata de registro de preços (art. 86).

Dois limites legais numéricos e verificáveis, que é o que torna o achado indefensável de contestar:
· **§4º** — cada aderente pode adquirir até 50% do quantitativo registrado do item;
· **§5º** — a soma de TODAS as adesões não pode passar do dobro do quantitativo do item.

Ultrapassar qualquer um deles é violação objetiva, não juízo de valor.

Sem rede, sem banco.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.x4_carona_abusiva import (
    LIMITE_ADESAO_INDIVIDUAL,
    LIMITE_TOTAL_ADESOES,
    X4CaronaAbusiva,
)

_P = {"processo": "SEI-TESTE/000018/2026"}


def _ata(qtd: float = 1000.0) -> dict:
    return {"orgao_gerenciador": "SEPLAG",
            "itens": [{"item": "cartucho", "quantitativo_registrado": qtd}]}


def _ades(*pares) -> list[dict]:
    return [{"item": "cartucho", "aderente": a, "quantidade": q} for a, q in pares]


def test_limites_sao_os_do_art_86():
    assert LIMITE_ADESAO_INDIVIDUAL == 0.50
    assert LIMITE_TOTAL_ADESOES == 2.0


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_sem_ata_e_nao_avaliavel():
    res = X4CaronaAbusiva().avaliar({**_P, "adesoes": _ades(("Org A", 100))})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_sem_adesoes_nao_ha_carona_a_aferir():
    res = X4CaronaAbusiva().avaliar({**_P, "ata": _ata()})
    assert res.status == "nao_avaliavel"
    assert res.valores["n_adesoes"] == 0


def test_item_sem_quantitativo_registrado_nao_entra_nos_limites():
    """Sem denominador não há fração — e inventá-lo produziria percentual falso."""
    ata = {"orgao_gerenciador": "X", "itens": [{"item": "cartucho"}]}
    res = X4CaronaAbusiva().avaliar({**_P, "ata": ata, "adesoes": _ades(("Org A", 9999))})
    assert res.valores["n_itens_registrados"] == 0
    assert res.score == 0.0


# ───────────────────────────── §4º: limite individual ─────────────────────────────────────────

def test_adesao_individual_acima_de_50_por_cento_viola_o_paragrafo_4():
    res = X4CaronaAbusiva().avaliar({**_P, "ata": _ata(1000), "adesoes": _ades(("Org A", 600))})
    assert res.score >= ANCORAS["critico"] or res.score == pytest.approx(1.0)
    assert res.valores["violacoes_individuais_50pct"]
    assert res.valores["violacoes_individuais_50pct"][0]["fracao"] == pytest.approx(0.6)
    assert "§4º" in res.motivo_refutacao


def test_adesao_individual_no_limite_nao_viola():
    """Exatamente 50% é o que a lei permite — violação exige ultrapassar."""
    res = X4CaronaAbusiva().avaliar({**_P, "ata": _ata(1000), "adesoes": _ades(("Org A", 500))})
    assert res.valores["violacoes_individuais_50pct"] == []


def test_adesoes_do_mesmo_aderente_somam_para_o_limite_individual():
    """Fatiar a adesão em duas não escapa do teto — o detector agrega por (item, aderente)."""
    res = X4CaronaAbusiva().avaliar({**_P, "ata": _ata(1000),
                                     "adesoes": _ades(("Org A", 300), ("Org A", 300))})
    assert res.valores["violacoes_individuais_50pct"]


# ───────────────────────────── §5º: limite total ──────────────────────────────────────────────

def test_soma_das_adesoes_acima_do_dobro_viola_o_paragrafo_5():
    adesoes = _ades(("Org A", 400), ("Org B", 400), ("Org C", 400), ("Org D", 900))
    res = X4CaronaAbusiva().avaliar({**_P, "ata": _ata(1000), "adesoes": adesoes})
    assert res.score >= ANCORAS["critico"] or res.score == pytest.approx(1.0)
    assert res.valores["violacoes_total_dobro"]


def test_varias_adesoes_pequenas_dentro_do_dobro_nao_violam():
    adesoes = _ades(("Org A", 400), ("Org B", 400), ("Org C", 400))
    res = X4CaronaAbusiva().avaliar({**_P, "ata": _ata(1000), "adesoes": adesoes})
    assert res.valores["violacoes_total_dobro"] == []
    assert res.valores["violacoes_individuais_50pct"] == []
    assert res.score == 0.0


def test_razao_adesoes_sobre_origem_e_registrada_como_contexto():
    """A curva de multiplicação do dano é sinal de contexto — vai nos valores, não vira achado."""
    adesoes = _ades(("Org A", 400), ("Org B", 400))
    res = X4CaronaAbusiva().avaliar({**_P, "ata": _ata(1000), "adesoes": adesoes})
    assert res.valores["razao_adesoes_origem_por_item"]["cartucho"] == pytest.approx(0.8)


# ───────────────────────────── robustez e schema ──────────────────────────────────────────────

def test_lixo_na_lista_de_adesoes_nao_quebra():
    adesoes = _ades(("Org A", 600)) + [None, "texto", {"item": None}, {"quantidade": None}]
    res = X4CaronaAbusiva().avaliar({**_P, "ata": _ata(1000), "adesoes": adesoes})
    assert res.status in STATUS_VALIDOS
    assert res.valores["n_adesoes"] == 1


def test_conta_aderentes_distintos():
    adesoes = _ades(("Org A", 100), ("Org A", 100), ("Org B", 100))
    res = X4CaronaAbusiva().avaliar({**_P, "ata": _ata(1000), "adesoes": adesoes})
    assert res.valores["n_aderentes_distintos"] == 2


def test_schema_de_saida_conforme_spec():
    d = X4CaronaAbusiva().avaliar({**_P, "ata": _ata(1000),
                                   "adesoes": _ades(("Org A", 600))}).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "X4"
    assert d["status"] in STATUS_VALIDOS
