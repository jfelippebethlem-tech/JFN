# -*- coding: utf-8 -*-
"""Rede de proteção do detector J3 — desconto anômalo / irrisório recorrente.

Screen estrutural de competição: o vencedor fechou rente ao teto? Isso é sinal, não prova — e o
detector carrega uma exculpatória forte (commodity e preço tabelado têm desconto naturalmente
baixo e LÍCITO). Os testes abaixo trancam justamente esse equilíbrio.

Sem rede, sem banco.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.j3_desconto_anomalo import (
    J3DescontoAnomalo,
    _desconto,
    _num,
)

_P = {"processo": "SEI-TESTE/000002/2026"}


def _serie(n: int, desconto: float) -> list[dict]:
    """Série sintética de certames do órgão, todos com o mesmo desconto."""
    return [{"valor_estimado": 100.0, "valor_homologado": 100.0 * (1 - desconto)} for _ in range(n)]


# ───────────────────────────── régua objetiva: cálculo do desconto ────────────────────────────

@pytest.mark.parametrize("estimado,homologado,esperado", [
    (100.0, 90.0, 0.10),
    (100.0, 100.0, 0.0),
    (100.0, 110.0, -0.10),   # homologado ACIMA do estimado
])
def test_calcula_desconto(estimado, homologado, esperado):
    assert _desconto(estimado, homologado) == pytest.approx(esperado)


@pytest.mark.parametrize("estimado", [0.0, -50.0, None])
def test_estimado_nao_positivo_nao_produz_desconto(estimado):
    """Divisão por estimativa zero/negativa não pode virar número — vira None."""
    assert _desconto(estimado, 90.0) is None


def test_booleano_nao_e_numero():
    """`True` é int em Python e passaria por número — o guard existe justamente para isso."""
    assert _num(True) is None
    assert _num(1.0) == 1.0


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

@pytest.mark.parametrize("ctx", [
    {},
    {"valor_estimado": 100.0},
    {"valor_homologado": 90.0},
    {"valor_estimado": 0.0, "valor_homologado": 90.0},
])
def test_sem_base_de_calculo_e_nao_avaliavel(ctx):
    """INDISPONÍVEL ≠ 0: sem estimado>0 e homologado não há juízo possível."""
    res = J3DescontoAnomalo().avaliar({**_P, **ctx})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "não inventamos número" in res.motivo_refutacao


# ───────────────────────────── homologado acima do estimado ───────────────────────────────────

def test_homologado_acima_do_estimado_e_violacao_objetiva():
    """Não é 'desconto baixo': proposta acima do orçamento devia ter sido DESCLASSIFICADA."""
    res = J3DescontoAnomalo().avaliar({**_P, "valor_estimado": 100.0, "valor_homologado": 110.0})
    assert res.score >= ANCORAS["forte"]
    assert res.status == "confirmado"
    assert "art. 59 III" in res.motivo_refutacao
    assert res.evidencia


def test_homologado_acima_pontua_mesmo_com_item_regulado():
    """A exculpatória de preço tabelado vale para desconto BAIXO, nunca para homologar ACIMA do teto."""
    res = J3DescontoAnomalo().avaliar({**_P, "valor_estimado": 100.0, "valor_homologado": 110.0,
                                       "item_preco_regulado": True})
    assert res.score >= ANCORAS["forte"]


# ───────────────────────────── desconto irrisório e sua exculpatória ──────────────────────────

def test_desconto_irrisorio_pontua_medio():
    res = J3DescontoAnomalo().avaliar({**_P, "valor_estimado": 100.0, "valor_homologado": 99.0})
    assert res.score == pytest.approx(ANCORAS["medio"])
    assert res.valores["desconto_pct"] == pytest.approx(1.0)


def test_item_de_preco_regulado_e_exculpatoria_e_nao_pontua():
    """Combustível e medicamento CMED têm margem fina: 1% de desconto é lícito e esperado.

    Sem este guard, o detector acusaria toda compra de commodity do Estado.
    """
    res = J3DescontoAnomalo().avaliar({**_P, "valor_estimado": 100.0, "valor_homologado": 99.0,
                                       "item_preco_regulado": True})
    assert res.score == 0.0
    assert res.status == "descartado"
    assert "REGULADO" in res.motivo_refutacao or "regulado" in res.motivo_refutacao.lower()


def test_desconto_saudavel_nao_inventa_indicio():
    res = J3DescontoAnomalo().avaliar({**_P, "valor_estimado": 100.0, "valor_homologado": 80.0})
    assert res.status == "descartado"
    assert res.score == 0.0
    assert res.explicacao_inocente


# ───────────────────────────── baseline de categoria ──────────────────────────────────────────

def test_desconto_muito_abaixo_do_baseline_da_categoria_pontua():
    """5% num mercado que desconta 30% é decil inferior estrutural — mesmo não sendo irrisório."""
    res = J3DescontoAnomalo().avaliar({**_P, "valor_estimado": 100.0, "valor_homologado": 95.0,
                                       "desconto_mercado_categoria": 0.30})
    assert res.score >= ANCORAS["medio"]
    assert "baseline" in res.motivo_refutacao


def test_baseline_da_categoria_vence_o_do_orgao():
    """O baseline externo (categoria) é mais confiável que o interno (o próprio órgão pode estar viciado)."""
    res = J3DescontoAnomalo().avaliar({**_P, "valor_estimado": 100.0, "valor_homologado": 95.0,
                                       "desconto_mercado_categoria": 0.06,
                                       "desconto_medio_orgao": 0.90})
    assert res.valores["desconto_mercado_categoria"] == 0.06
    assert res.score == 0.0, "5% não está abaixo da metade de 6% — a categoria manda"


def test_baseline_nao_pontua_para_item_regulado():
    res = J3DescontoAnomalo().avaliar({**_P, "valor_estimado": 100.0, "valor_homologado": 95.0,
                                       "desconto_mercado_categoria": 0.30,
                                       "item_preco_regulado": True})
    assert res.score == 0.0


# ───────────────────────────── recorrência ────────────────────────────────────────────────────

def test_serie_curta_nao_afirma_recorrencia():
    """Um punhado de certames não sustenta 'recorrente' — a spec exige 12. Honesto: nao_avaliavel."""
    res = J3DescontoAnomalo().avaliar({**_P, "valor_estimado": 100.0, "valor_homologado": 80.0,
                                       "serie_certames_orgao": _serie(5, 0.005)})
    assert res.score == 0.0
    assert "recorrencia" in res.valores


def test_serie_longa_com_desconto_irrisorio_e_recorrencia_forte():
    res = J3DescontoAnomalo().avaliar({**_P, "valor_estimado": 100.0, "valor_homologado": 80.0,
                                       "serie_certames_orgao": _serie(12, 0.005)})
    assert res.score >= ANCORAS["forte"]
    assert res.status == "confirmado"


def test_serie_longa_com_desconto_saudavel_nao_pontua():
    """Guard: série grande por si não é indício — o que conta é o PADRÃO dentro dela."""
    res = J3DescontoAnomalo().avaliar({**_P, "valor_estimado": 100.0, "valor_homologado": 80.0,
                                       "serie_certames_orgao": _serie(24, 0.25)})
    assert res.score == 0.0
    assert res.status == "descartado"


def test_serie_com_lixo_nao_quebra():
    serie = _serie(12, 0.005) + [None, "texto", {}, {"valor_estimado": "x"}]
    res = J3DescontoAnomalo().avaliar({**_P, "valor_estimado": 100.0, "valor_homologado": 80.0,
                                       "serie_certames_orgao": serie})
    assert res.status in STATUS_VALIDOS


# ───────────────────────────── schema §1.4 ────────────────────────────────────────────────────

def test_schema_de_saida_conforme_spec():
    res = J3DescontoAnomalo().avaliar({**_P, "valor_estimado": 100.0, "valor_homologado": 99.0})
    d = res.to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "J3"
    assert 0.0 <= d["score"] <= 1.0


def test_explicacao_inocente_sempre_presente_quando_pontua():
    """Regra do projeto: indício ≠ acusação. Todo achado sai com a hipótese que o derrubaria."""
    res = J3DescontoAnomalo().avaliar({**_P, "valor_estimado": 100.0, "valor_homologado": 99.0})
    assert res.score > 0
    assert res.explicacao_inocente
