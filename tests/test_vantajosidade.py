# -*- coding: utf-8 -*-
"""Vantajosidade da prorrogação — o teste que a lei exige e que ninguém computava.

O X2 já pontua a perpetuidade e já tem a rubrica `real / pro_forma / ausente`. Só que ela era
LLM-opcional e nada a alimentava: `varredura_execucao_ctx` devolve `pesquisa_vantajosidade: None`
porque a base não guarda o campo. O eixo mais decisivo da prorrogação ficava sempre
`nao_avaliavel`.

A decisão de desenho que define o módulo, e é o teste mais importante daqui: **sem referência de
mercado o veredito é `nao_aferivel`, não "sem achado"**. A ausência da pesquisa É o vício que o
art. 107 quer evitar — devolver "nada consta" deixaria o leitor concluir regularidade a partir da
falta de dado.
"""
from __future__ import annotations

import pytest

from compliance_agent.vantajosidade import avaliar, classe_para_x2

_MERCADO = [100.0, 102.0, 98.0, 101.0, 99.0, 100.0]


# ───────────────────────── a ausência de pesquisa É o achado ──────────────────────────────────

def test_sem_referencia_de_mercado_e_NAO_AFERIVEL_nao_sem_achado():
    r = avaliar(valor_atual=150.0)
    assert r["veredito"] == "nao_aferivel"
    assert "dever da Administração" in r["motivo"]
    assert "a própria ausência é o achado" in r["diligencia"]


def test_sem_valor_atual_tambem_nao_afere():
    r = avaliar(valor_atual=None, precos_mercado=_MERCADO)
    assert r["veredito"] == "nao_aferivel" and "ausente ≠ zero" in r["motivo"]


# ───────────────────────── 1 · preço acima do mercado ─────────────────────────────────────────

def test_contrato_muito_acima_do_mercado_e_desvantajoso():
    r = avaliar(valor_atual=140.0, precos_mercado=_MERCADO, fonte_mercado="Painel de Preços")
    assert r["veredito"] == "desvantajosa" and r["nivel"] == "forte"
    assert any(s["regra"] == "preco_acima_do_mercado" for s in r["sinais"])


def test_diferenca_pequena_nao_sustenta_afirmacao():
    """Variação de 10% entre contratações do mesmo objeto é comum."""
    r = avaliar(valor_atual=105.0, precos_mercado=_MERCADO, fonte_mercado="Painel")
    assert r["veredito"] == "vantajosa"


def test_faixa_intermediaria_e_medio():
    r = avaliar(valor_atual=115.0, precos_mercado=_MERCADO, fonte_mercado="Painel")
    assert r["veredito"] == "desvantajosa" and r["nivel"] == "medio"


def test_grupo_de_referencia_heterogeneo_vira_lacuna_nao_achado():
    """Reusa o portão de homogeneidade — comparar coisas diferentes inventa desvantagem."""
    r = avaliar(valor_atual=500.0, precos_mercado=[1.0, 5.0, 12.0, 800.0, 1292.0, 40.0],
                fonte_mercado="Painel")
    assert r["veredito"] == "vantajosa"     # nenhum sinal se sustenta
    assert any("prejudicada" in x for x in r["lacunas"])


# ───────────────────────── 2 · reajuste acima do índice ───────────────────────────────────────

def test_reajuste_acima_do_indice_setorial_corroi_a_vantagem():
    r = avaliar(valor_atual=100.0, precos_mercado=_MERCADO, fonte_mercado="Painel",
                reajuste_aplicado=0.12, indice_setorial=0.05)
    assert r["veredito"] == "desvantajosa"
    assert any(s["regra"] == "reajuste_acima_do_indice" for s in r["sinais"])
    assert "nenhum ato isolado pareça irregular" in r["motivo"]


def test_reajuste_dentro_do_indice_nao_dispara():
    r = avaliar(valor_atual=100.0, precos_mercado=_MERCADO, fonte_mercado="Painel",
                reajuste_aplicado=0.05, indice_setorial=0.05)
    assert r["veredito"] == "vantajosa"


def test_indice_ausente_vira_lacuna_declarada():
    r = avaliar(valor_atual=100.0, precos_mercado=_MERCADO, fonte_mercado="Painel",
                reajuste_aplicado=0.12)
    assert any("índice setorial" in x for x in r["lacunas"])


# ───────────────────────── 3 · vantagem decrescente ───────────────────────────────────────────

def test_serie_que_piora_a_cada_renovacao():
    """Um ponto no tempo não mostra isso; a série mostra."""
    r = avaliar(valor_atual=100.0, precos_mercado=_MERCADO, fonte_mercado="Painel",
                historico_desvantagem=[0.02, 0.08, 0.15, 0.22])
    assert any(s["regra"] == "vantagem_decrescente" for s in r["sinais"])


def test_serie_estavel_nao_dispara():
    r = avaliar(valor_atual=100.0, precos_mercado=_MERCADO, fonte_mercado="Painel",
                historico_desvantagem=[0.10, 0.08, 0.11, 0.09])
    assert not any(s["regra"] == "vantagem_decrescente" for s in r["sinais"])


def test_serie_curta_vira_lacuna():
    r = avaliar(valor_atual=100.0, precos_mercado=_MERCADO, fonte_mercado="Painel",
                historico_desvantagem=[0.02, 0.20])
    assert any("série curta" in x for x in r["lacunas"])


# ───────────────────────── ponte com o X2 ─────────────────────────────────────────────────────

def test_traducao_para_a_rubrica_do_X2():
    assert classe_para_x2(avaliar(valor_atual=150.0)) == "ausente"
    assert classe_para_x2(avaliar(valor_atual=140.0, precos_mercado=_MERCADO,
                                  fonte_mercado="P")) == "pro_forma"
    assert classe_para_x2(avaliar(valor_atual=100.0, precos_mercado=_MERCADO,
                                  fonte_mercado="P")) == "real"


def test_traducao_recusa_o_que_nao_e_deterministico():
    """Sobrescrever a rubrica do LLM com chute pioraria o X2."""
    assert classe_para_x2({}) is None
    assert classe_para_x2({"veredito": "nao_aferivel", "lacunas": ["outra coisa"]}) is None


def test_a_classe_traduzida_e_aceita_pela_rubrica_do_X2():
    """Fecha o círculo: o vocabulário tem de casar com o que o card espera."""
    from compliance_agent.detectores.x2_prorrogacao_perpetua import _RUBRICA_VANTAJOSIDADE

    for valor in (150.0, 140.0, 100.0):
        c = classe_para_x2(avaliar(valor_atual=valor, precos_mercado=_MERCADO,
                                   fonte_mercado="P") if valor != 150.0
                           else avaliar(valor_atual=valor))
        assert c in _RUBRICA_VANTAJOSIDADE


# ───────────────────────── contrato de saída ──────────────────────────────────────────────────

def test_achado_traz_explicacao_inocente_e_diligencia():
    r = avaliar(valor_atual=140.0, precos_mercado=_MERCADO, fonte_mercado="Painel")
    assert "escopo maior" in r["explicacao_inocente"]
    assert "memória de cálculo" in r["diligencia"]


def test_sinais_saem_do_mais_grave_para_o_menos():
    r = avaliar(valor_atual=140.0, precos_mercado=_MERCADO, fonte_mercado="Painel",
                reajuste_aplicado=0.12, indice_setorial=0.05)
    assert r["sinais"][0]["nivel"] == "forte"
