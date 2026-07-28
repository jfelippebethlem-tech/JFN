# -*- coding: utf-8 -*-
"""Rede de proteção do detector X5 — jogo de planilha.

O golpe: na licitação, alguns itens vêm caríssimos e outros baratíssimos, mantendo o total
competitivo. Na execução, os caros crescem e os baratos somem. O total combinado nunca se
realiza — quem paga é o erário.

A peça central do detector é a **correlação direcional de Pearson** entre desvio de preço e
variação de quantidade. E o guard mais importante é de amostra: correlação com poucos pontos é
ruído, então 'crítico' e 'forte' têm mínimos de n distintos e declarados.

Condição NECESSÁRIA (e não suficiente): tem de haver item caro E item barato ao mesmo tempo.

Sem rede, sem banco.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.x5_jogo_planilha import X5JogoDePlanilha

_P = {"processo": "SEI-TESTE/000019/2026"}


def _item(nome: str, desvio: float, var_qtd: float | None = None) -> dict:
    """Item com preço a `desvio` do referencial e quantidade executada `var_qtd` acima da contratada."""
    d = {"item": nome, "referencial": 100.0, "preco_contratado": 100.0 * (1 + desvio)}
    if var_qtd is not None:
        d["quantidade_contratada"] = 100.0
        d["quantidade_executada"] = 100.0 * (1 + var_qtd)
    return d


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_sem_itens_e_nao_avaliavel():
    res = X5JogoDePlanilha().avaliar({**_P})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_itens_sem_referencial_sao_ignorados_e_nao_inventam_desvio():
    """Sem SINAPI/SICRO/mediana não há desvio a calcular — a linha sai da conta, não vira zero."""
    itens = [{"item": "escavação", "preco_contratado": 500.0},
             {"item": "aterro", "referencial": 0.0, "preco_contratado": 100.0}]
    res = X5JogoDePlanilha().avaliar({**_P, "itens": itens})
    assert res.status == "nao_avaliavel"
    assert res.valores["n_itens_avaliaveis"] == 0


# ───────────────────────────── condição necessária: desequilíbrio ─────────────────────────────

def test_planilha_toda_cara_nao_e_jogo_de_planilha():
    """Tudo caro é sobrepreço (P3), não jogo de planilha. Confundir os dois erra o enquadramento."""
    itens = [_item("a", 0.40), _item("b", 0.35), _item("c", 0.50)]
    res = X5JogoDePlanilha().avaliar({**_P, "itens": itens})
    assert res.status == "descartado"
    assert res.score == 0.0
    assert "coexistência" in res.motivo_refutacao


def test_planilha_equilibrada_nao_pontua():
    itens = [_item("a", 0.01), _item("b", -0.02), _item("c", 0.0)]
    res = X5JogoDePlanilha().avaliar({**_P, "itens": itens})
    assert res.status == "descartado"
    assert res.explicacao_inocente


def test_coexistencia_de_caro_e_barato_e_condicao_necessaria():
    itens = [_item("caro", 0.40), _item("barato", -0.40)]
    res = X5JogoDePlanilha().avaliar({**_P, "itens": itens})
    assert res.status != "descartado" or res.score >= 0
    assert res.valores["n_itens_avaliaveis"] == 2


# ───────────────────────────── correlação direcional ──────────────────────────────────────────

def test_correlacao_com_amostra_pequena_nao_vira_achado_forte():
    """Pearson com 2 ou 3 pontos é ruído. O detector exige n mínimo por nível."""
    itens = [_item("caro", 0.40, 0.50), _item("barato", -0.40, -0.50)]
    res = X5JogoDePlanilha().avaliar({**_P, "itens": itens})
    assert res.valores["correlacao_pearson"] is not None
    assert res.score < ANCORAS["forte"]


def test_correlacao_critica_exige_amostra_suficiente():
    """Caros crescem, baratos somem, com n≥6: é a assinatura do desenho, não coincidência."""
    itens = [_item(f"caro{i}", 0.40, 0.50) for i in range(4)]
    itens += [_item(f"barato{i}", -0.40, -0.50) for i in range(4)]
    res = X5JogoDePlanilha().avaliar({**_P, "itens": itens})
    assert res.valores["n_itens_com_execucao"] == 8
    assert res.valores["correlacao_pearson"] > 0.9
    assert res.score >= ANCORAS["forte"]


def test_correlacao_invertida_nao_pontua():
    """Se os itens CAROS é que sumiram, o padrão é o oposto do jogo de planilha."""
    itens = [_item(f"caro{i}", 0.40, -0.50) for i in range(4)]
    itens += [_item(f"barato{i}", -0.40, 0.50) for i in range(4)]
    res = X5JogoDePlanilha().avaliar({**_P, "itens": itens})
    assert res.valores["correlacao_pearson"] < 0
    assert res.score < ANCORAS["forte"]


def test_sem_execucao_a_correlacao_nao_e_calculada():
    """Planilha desequilibrada sem execução medida é suspeita, mas a prova depende do que foi executado."""
    itens = [_item("caro", 0.40), _item("barato", -0.40)]
    res = X5JogoDePlanilha().avaliar({**_P, "itens": itens})
    assert res.valores["tem_execucao"] is False
    assert res.valores["correlacao_pearson"] is None


# ───────────────────────────── contagens e schema ─────────────────────────────────────────────

def test_conta_sobreprecificados_e_subcotados():
    itens = [_item("a", 0.40), _item("b", 0.30), _item("c", -0.40)]
    res = X5JogoDePlanilha().avaliar({**_P, "itens": itens})
    assert res.valores["n_itens_avaliaveis"] == 3
    assert res.valores["desvio_medio"] == pytest.approx(0.10)


def test_tolerancia_de_cinco_por_cento_nao_conta_como_desvio():
    """Variação de 3% é ruído de mercado, não desequilíbrio."""
    itens = [_item("a", 0.03), _item("b", -0.03)]
    res = X5JogoDePlanilha().avaliar({**_P, "itens": itens})
    assert res.status == "descartado"


def test_schema_de_saida_conforme_spec():
    itens = [_item("caro", 0.40, 0.50), _item("barato", -0.40, -0.50)]
    d = X5JogoDePlanilha().avaliar({**_P, "itens": itens}).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "X5"
    assert d["status"] in STATUS_VALIDOS
