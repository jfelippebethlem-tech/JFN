# -*- coding: utf-8 -*-
"""Rede de proteção do detector P3 — sobrepreço interno (mesmo item ≥2× entre órgãos).

A regra dura do spec P3: **item sem referência NÃO pontua sobrepreço**. Amostra insuficiente é
`nao_avaliavel`, nunca zero e nunca achado. O outro ponto delicado é o gate anti-outlier: razão
alta pode nascer de UM preço absurdamente baixo (erro de unidade no cadastro) e não de sobrepreço
— por isso a razão só sustenta 'forte' se o maior preço também desviar da MEDIANA.

Os testes injetam `achados` pré-computados (caminho previsto no docstring do detector), então
nada aqui depende de `precos_extract` nem toca banco.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.p3_sobrepreco import P3Sobrepreco, _nivel_por_razao

_P = {"processo": "ITEM-TESTE/0001"}


def _achado(razao: float, pct_med: float | None = None) -> list[dict]:
    return [{"item": "cartucho de toner", "razao_max_min": razao, "min": 100.0,
             "max": 100.0 * razao, "sobrepreco_pct_vs_mediana": pct_med}]


# ───────────────────────────── régua: nível por razão ─────────────────────────────────────────

@pytest.mark.parametrize("razao,esperado", [
    (2.0, "fraco"),
    (2.9, "fraco"),
    (3.0, "medio"),
    (3.9, "medio"),
    (4.0, "forte"),
    (12.0, "forte"),
])
def test_nivel_por_razao_sem_sinal_robusto(razao, esperado):
    """Sem `pct_vs_mediana` o comportamento é o legado: só a razão decide."""
    assert _nivel_por_razao(razao) == esperado


@pytest.mark.parametrize("razao,pct_med,esperado", [
    (5.0, 150.0, "forte"),   # razão alta E desvio robusto alto → forte de verdade
    (5.0, 70.0, "medio"),    # razão alta mas desvio moderado → rebaixa
    (5.0, 10.0, "fraco"),    # razão alta sem desvio robusto → é outlier BAIXO, não sobrepreço
    (3.5, 60.0, "medio"),
    (3.5, 20.0, "fraco"),
])
def test_gate_anti_outlier_rebaixa_quando_a_mediana_nao_confirma(razao, pct_med, esperado):
    """Razão 5× com o maior preço colado na mediana significa que o MENOR é que está errado
    (erro de unidade: 'caixa' cadastrada como 'unidade'). Acusar sobrepreço aí é falso positivo."""
    assert _nivel_por_razao(razao, pct_med) == esperado


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_sem_registros_e_nao_avaliavel_nao_zero():
    res = P3Sobrepreco().avaliar({**_P, "registros": []})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "sem_referencial" in res.motivo_refutacao


def test_amostra_insuficiente_e_sem_referencial_nao_descartado():
    """Distinção que importa: 'não deu para comparar' ≠ 'comparei e está tudo bem'.

    Dois registros do mesmo item, com min_amostras=3: não há base. Marcar 'descartado' aqui
    diria ao fiscal que o item foi verificado e aprovado — o que é falso.
    """
    registros = [{"descricao": "cartucho de toner", "preco_unitario": 100.0},
                 {"descricao": "cartucho de toner", "preco_unitario": 900.0}]
    res = P3Sobrepreco().avaliar({**_P, "registros": registros, "achados": [], "min_amostras": 3})
    assert res.status == "nao_avaliavel"
    assert "sem_referencial" in res.motivo_refutacao


def test_amostra_suficiente_sem_dispersao_e_descartado():
    """Aqui sim houve comparação real e nada apareceu — pode dizer 'descartado'."""
    registros = [{"descricao": "cartucho de toner", "preco_unitario": p}
                 for p in (100.0, 105.0, 98.0, 102.0)]
    res = P3Sobrepreco().avaliar({**_P, "registros": registros, "achados": [], "min_amostras": 3})
    assert res.status == "descartado"
    assert res.score == 0.0
    assert res.explicacao_inocente


# ───────────────────────────── achado ─────────────────────────────────────────────────────────

def test_sobrepreco_forte_com_sinal_robusto():
    res = P3Sobrepreco().avaliar({**_P, "achados": _achado(6.0, 200.0)})
    assert res.status == "confirmado"
    assert res.score == pytest.approx(ANCORAS["forte"])
    assert res.valores["razao_max_min"] == 6.0
    assert res.valores["item"] == "cartucho de toner"


def test_razao_alta_sem_desvio_da_mediana_nao_vira_achado_forte():
    """O caso do erro de unidade: 6× de razão, mas o maior preço mal desvia da mediana."""
    res = P3Sobrepreco().avaliar({**_P, "achados": _achado(6.0, 5.0)})
    assert res.score == pytest.approx(ANCORAS["fraco"])


def test_conta_quantos_itens_foram_flagrados():
    achados = _achado(6.0, 200.0) + _achado(3.2, 80.0)
    res = P3Sobrepreco().avaliar({**_P, "achados": achados})
    assert res.valores["n_itens_flagrados"] == 2


def test_usa_o_primeiro_achado_que_e_o_de_maior_razao():
    """`sobrepreco_interno` já devolve ordenado desc — o detector confia nisso."""
    achados = _achado(9.0, 300.0) + _achado(2.1, 10.0)
    res = P3Sobrepreco().avaliar({**_P, "achados": achados})
    assert res.valores["razao_max_min"] == 9.0


# ───────────────────────────── robustez ───────────────────────────────────────────────────────

def test_modulo_de_precos_indisponivel_degrada_honesto(monkeypatch):
    """Sem `achados` o detector chama `precos_extract`; se ele falhar, declara — não zera."""
    import sys
    import types

    falso = types.ModuleType("compliance_agent.precos_extract")

    def _explode(*a, **k):
        raise RuntimeError("módulo de preços fora do ar")

    falso.sobrepreco_interno = _explode
    falso._norm = lambda s: str(s or "").strip().lower()
    monkeypatch.setitem(sys.modules, "compliance_agent.precos_extract", falso)

    res = P3Sobrepreco().avaliar({**_P, "registros": [{"descricao": "x", "preco_unitario": 1.0}]})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "indisponível" in res.motivo_refutacao


def test_min_amostras_configuravel():
    registros = [{"descricao": "cartucho de toner", "preco_unitario": p} for p in (100.0, 900.0)]
    frouxo = P3Sobrepreco().avaliar({**_P, "registros": registros, "achados": [], "min_amostras": 2})
    assert frouxo.status == "descartado", "com 2 amostras já dá para comparar"
    rigido = P3Sobrepreco().avaliar({**_P, "registros": registros, "achados": [], "min_amostras": 5})
    assert rigido.status == "nao_avaliavel"


# ───────────────────────────── schema §1.4 ────────────────────────────────────────────────────

def test_schema_de_saida_conforme_spec():
    res = P3Sobrepreco().avaliar({**_P, "achados": _achado(6.0, 200.0)})
    d = res.to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "P3"
    assert d["status"] in STATUS_VALIDOS
    assert 0.0 <= d["score"] <= 1.0
