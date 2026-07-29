# -*- coding: utf-8 -*-
"""Economicidade — a confusão jurídica e a confusão estatística, ambas já medidas nesta casa.

**Jurídica:** sobrepreço é vício do orçamento; superfaturamento é DANO, e dano exige execução
medida e pagamento comprovado em Ordem Bancária. Chamar um de outro é afirmar prejuízo que não se
provou — e o art. 10 da Lei 8.429 exige perda patrimonial "efetiva e comprovadamente" demonstrada.

**Estatística:** 60% de uma manchete de economia desta casa comparava produtos diferentes; "peça
de veículo" tem dispersão de 1292× entre itens que o catálogo trata como o mesmo, e a manchete
caiu de R$ 15,6 mi para R$ 6,2 mi quando só o homogêneo entrou.
"""
from __future__ import annotations

import pytest

from compliance_agent.knowledge.economicidade import (
    SOBREPRECO,
    SUPERFATURAMENTO,
    avaliar,
    homogeneidade,
    intervalo_economia,
    melhor_referencia,
)

_REF = [100.0, 102.0, 98.0, 101.0, 99.0, 100.0]     # grupo homogêneo, n=6


# ───────────────────────── sobrepreço × superfaturamento ──────────────────────────────────────

def test_preco_acima_da_referencia_sem_pagamento_e_SOBREPRECO():
    r = avaliar(150.0, _REF, fonte_referencia="Painel de Preços", data_referencia="2026-07")
    assert r["classificacao"] == SOBREPRECO
    assert "Empenho não é pagamento" in r["lacuna"]


def test_com_pagamento_em_OB_vira_SUPERFATURAMENTO_com_memoria_de_calculo():
    r = avaliar(150.0, _REF, fonte_referencia="SINAPI", quantidade_executada=10,
                pago_ob=1500.0)
    assert r["classificacao"] == SUPERFATURAMENTO
    assert r["dano"] == pytest.approx(500.0)
    assert "quantidade executada" in r["memoria_de_calculo"]


def test_pagamento_sem_quantidade_executada_declara_o_dano_nao_quantificado():
    r = avaliar(150.0, _REF, fonte_referencia="SINAPI", pago_ob=1500.0)
    assert r["classificacao"] == SUPERFATURAMENTO and r["dano"] is None
    assert "não está quantificado" in r["lacuna"]


def test_preco_abaixo_da_referencia_nao_e_achado():
    r = avaliar(90.0, _REF, fonte_referencia="SINAPI")
    assert r["classificacao"] is None


def test_definicoes_saem_junto_para_quem_le_o_relatorio():
    r = avaliar(150.0, _REF, fonte_referencia="SINAPI")
    assert r["definicoes"][SUPERFATURAMENTO]["exige_execucao"].startswith("sim")
    assert "Ordem Bancária" in r["definicoes"][SUPERFATURAMENTO]["prova"]


# ───────────────────────── o portão de homogeneidade ──────────────────────────────────────────

def test_grupo_com_dispersao_absurda_nao_e_comparavel():
    """'peça de veículo': 1292× entre o mais barato e o mais caro do MESMO código."""
    r = homogeneidade([1.0, 5.0, 12.0, 800.0, 1292.0, 40.0])
    assert r["comparavel"] is False
    assert "itens DIFERENTES" in r["motivo"]


def test_grupo_homogeneo_passa():
    assert homogeneidade(_REF)["comparavel"] is True


def test_amostra_pequena_nao_e_referencia():
    r = homogeneidade([100.0, 101.0])
    assert r["comparavel"] is False and "n=2" in r["motivo"]


def test_grupo_nao_comparavel_vira_achado_de_PLANEJAMENTO_nao_de_preco():
    """A descrição genérica é que impede a aferição — e isso é vício do art. 40."""
    r = avaliar(500.0, [1.0, 5.0, 12.0, 800.0, 1292.0, 40.0], fonte_referencia="Painel")
    assert r["aferivel"] is False
    assert r["achado_alternativo"]["familia"] == "planejamento"
    assert "art. 40" in r["achado_alternativo"]["descricao"]


def test_referencia_sem_fonte_nao_sustenta_glosa():
    r = avaliar(150.0, _REF, fonte_referencia="")
    assert r["aferivel"] is False and "sem fonte" in r["motivo"]


def test_preco_ausente_nao_vira_zero():
    r = avaliar(None, _REF, fonte_referencia="SINAPI")
    assert r["aferivel"] is False and "ausente ≠ zero" in r["motivo"]


# ───────────────────────── hierarquia da referência ───────────────────────────────────────────

def test_tabela_oficial_vence_pesquisa_com_fornecedores():
    r = melhor_referencia(["pesquisa_fornecedores", "sinapi"], tipo_objeto="obras")
    assert r.id == "sinapi"


def test_emop_esta_disponivel_para_obra_estadual():
    assert melhor_referencia(["emop", "painel_precos"], tipo_objeto="obras").id == "emop"


def test_sinapi_avisa_sobre_desonerada():
    r = melhor_referencia(["sinapi"], tipo_objeto="obras")
    assert "desonerada" in r.observacao


def test_pesquisa_com_fornecedores_e_a_mais_fragil_e_diz_por_que():
    r = melhor_referencia(["pesquisa_fornecedores"])
    assert r.prioridade == 4 and "fachada" in r.observacao


def test_sem_referencia_disponivel_devolve_none():
    assert melhor_referencia([]) is None


# ───────────────────────── a manchete como intervalo ──────────────────────────────────────────

def test_economia_sai_como_intervalo_nao_como_numero_unico():
    r = intervalo_economia([6_200_000.0], [15_600_000.0])
    assert r["minimo"] == pytest.approx(6_200_000.0)
    assert r["maximo"] == pytest.approx(15_600_000.0)
    assert "somente grupos comparáveis" in r["texto"]


def test_intervalo_traz_a_ressalva_do_limite_superior():
    r = intervalo_economia([1.0], [2.0])
    assert "produtos diferentes" in r["ressalva"]


def test_estatistica_declarada_e_a_mediana():
    r = avaliar(150.0, _REF, fonte_referencia="SINAPI")
    assert "mediana" in r["estatistica"] and "65/2021" in r["estatistica"]
