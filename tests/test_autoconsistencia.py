# -*- coding: utf-8 -*-
"""Auto-consistência do veredito — e as três formas de agregar errado.

A casa já vota valor majoritário em EXTRAÇÃO (`nucleo/extracao_robusta`), e não votava nada em
JUÍZO: cada parecer era uma amostragem, tratada como se fosse determinística.

O que estes testes travam:

  1. **Média de âncora é invenção.** Média de 'verde' e 'vermelho' não é 'amarelo' — é um nível
     que nenhum voto afirmou. A agregação é mediana ORDINAL de nome, como o resto da casa.
  2. **Empate resolve para o menos severo.** Ao contrário da fusão det×LLM (onde prevalece o mais
     severo, porque as camadas são independentes), aqui as amostras vêm do MESMO modelo sobre o
     MESMO texto: a discordância mede incerteza, e na dúvida vale a presunção de legitimidade.
  3. **Divergência é resultado.** Suavizá-la em silêncio esconde de quem assina justamente a
     informação de que o juízo foi instável.
"""
from __future__ import annotations

import json

import pytest

from compliance_agent.nucleo.autoconsistencia import (
    aplicar,
    escalonar_por_severidade,
    votar,
)

ESCALA = ("verde", "amarelo", "vermelho")


def _sequencia(valores):
    """gerar() que devolve um valor por chamada, na ordem."""
    it = iter(valores)

    def gerar(_p, _s="", **_kw):
        return json.dumps({"grau": next(it)})
    return gerar


# ───────────────────────────── agregação ──────────────────────────────────────────────────────

def test_unanime_devolve_o_valor_sem_divergencia():
    r = votar(_sequencia(["amarelo"] * 3), "p", "s", escala=ESCALA)
    assert r["valor"] == "amarelo" and r["unanime"] is True and r["divergencia"] is None


def test_maioria_vence():
    r = votar(_sequencia(["vermelho", "vermelho", "verde"]), "p", "s", escala=ESCALA)
    assert r["valor"] == "vermelho"


def test_mediana_nunca_inventa_nivel_que_ninguem_votou():
    """Média de verde e vermelho daria 'amarelo' — nível que nenhuma amostra afirmou."""
    r = votar(_sequencia(["verde", "vermelho"]), "p", "s", escala=ESCALA, n=2)
    assert r["valor"] in {"verde", "vermelho"}
    assert r["valor"] != "amarelo"


def test_empate_resolve_para_o_MENOS_severo():
    """Discordância entre amostras do mesmo modelo mede incerteza — presunção de legitimidade."""
    r = votar(_sequencia(["verde", "vermelho"]), "p", "s", escala=ESCALA, n=2)
    assert r["valor"] == "verde"


def test_divergencia_e_declarada_com_amplitude_e_niveis():
    r = votar(_sequencia(["verde", "amarelo", "vermelho"]), "p", "s", escala=ESCALA)
    d = r["divergencia"]
    assert d and d["amplitude"] == 2
    assert d["niveis"] == ["verde", "amarelo", "vermelho"]
    assert "incerteza" in d["nota"]


# ───────────────────────────── honestidade ────────────────────────────────────────────────────

def test_nenhuma_amostra_valida_devolve_None_nao_o_nivel_mais_brando():
    r = votar(_sequencia(["indefinido", "sei_la", ""]), "p", "s", escala=ESCALA)
    assert r["valor"] is None and r["n_validos"] == 0
    assert "INDISPONÍVEL" in r["motivo"]


def test_amostra_que_estoura_nao_derruba_a_votacao():
    chamadas = {"n": 0}

    def gerar(_p, _s="", **_kw):
        chamadas["n"] += 1
        if chamadas["n"] == 2:
            raise RuntimeError("429")
        return json.dumps({"grau": "amarelo"})

    r = votar(gerar, "p", "s", escala=ESCALA)
    assert r["valor"] == "amarelo" and r["n_validos"] == 2


def test_resposta_nao_parseavel_nao_conta_como_voto():
    r = votar(lambda *_a, **_k: "desculpe", "p", "s", escala=ESCALA)
    assert r["valor"] is None


def test_gerar_sem_parametro_de_temperatura_continua_funcionando():
    """Não impor assinatura nova a quem já existe: o `gerar` da casa é (prompt, sistema)."""
    def gerar(_p, _s=""):
        return json.dumps({"grau": "amarelo"})

    r = votar(gerar, "p", "s", escala=ESCALA)
    assert r["valor"] == "amarelo"
    assert r["temperaturas_aplicadas"] == [None, None, None]


def test_gerar_com_temperatura_recebe_valores_distintos():
    vistos = []

    def gerar(_p, _s="", temperatura=None):
        vistos.append(temperatura)
        return json.dumps({"grau": "verde"})

    votar(gerar, "p", "s", escala=ESCALA)
    assert len(set(vistos)) == 3, "as amostras saíram todas com a mesma temperatura"


# ───────────────────────────── custo ──────────────────────────────────────────────────────────

def test_escalada_gasta_mais_so_no_caso_grave():
    assert escalonar_por_severidade("verde", escala=ESCALA, a_partir_de="amarelo") == 1
    assert escalonar_por_severidade("amarelo", escala=ESCALA, a_partir_de="amarelo") == 3
    assert escalonar_por_severidade("vermelho", escala=ESCALA, a_partir_de="amarelo") == 3


def test_grau_desconhecido_nao_escala_o_custo():
    assert escalonar_por_severidade("pendente_reprocessar", escala=ESCALA,
                                    a_partir_de="amarelo") == 1


# ───────────────────────────── aplicação ao veredito ──────────────────────────────────────────

def test_aplicar_escreve_o_valor_e_preserva_o_rastro():
    r = aplicar({"grau": "verde", "resumo": "x"},
                votar(_sequencia(["vermelho"] * 3), "p", "s", escala=ESCALA))
    assert r["grau"] == "vermelho" and r["resumo"] == "x"
    assert r["autoconsistencia"]["unanime"] is True
    assert r["autoconsistencia"]["valores"] == ["vermelho"] * 3


def test_aplicar_NAO_sobrescreve_com_None():
    """Votação indisponível deixa o veredito como estava — INDISPONÍVEL ≠ decidido."""
    r = aplicar({"grau": "amarelo"}, votar(lambda *_a, **_k: "lixo", "p", "s", escala=ESCALA))
    assert r["grau"] == "amarelo"
    assert r["autoconsistencia"]["n_validos"] == 0
