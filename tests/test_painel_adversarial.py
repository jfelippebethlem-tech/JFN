# -*- coding: utf-8 -*-
"""Painel adversarial — três lentes, três formas distintas de um achado ser falso.

O verificador que já existia é bom e é UMA chamada com UMA lente: "escreva a melhor explicação
inocente". Só que um achado pode ser falso por três razões diferentes, e a lente única investiga
apenas a primeira:

  (i)   o ato tem explicação administrativa lícita;
  (ii)  o dado está faltando e a ausência virou irregularidade — 59% das 9.863 red flags do sweep
        SEI eram exatamente isso, queixa de captura;
  (iii) o detector errou, casando com um falso positivo já conhecido da casa.

Redundância de lentes idênticas mede a mesma coisa três vezes. O que cobre falhas distintas são
lentes distintas — e é isso que estes testes travam, junto com a honestidade do quórum.
"""
from __future__ import annotations

import json

import pytest

from compliance_agent.detectores.base import (
    ResultadoDetector,
    aplicar_exculpatoria,
    painel_adversarial,
)

_EV = [{"fonte": "edital", "trecho": "exige atestado com 80% do objeto", "hash": "x",
        "capturado_em": "2026-07-29"}]


def _resp(refuta, motivo="m"):
    return json.dumps({"refuta": refuta, "motivo": motivo, "explicacao_inocente": "e"})


def _por_lente(mapa):
    """gerar() que responde conforme a hipótese injetada no system-prompt da lente."""
    def gerar(_prompt, sistema=""):
        for chave, resposta in mapa.items():
            if chave in sistema:
                return resposta
        return _resp(False)
    return gerar


def test_tres_lentes_com_hipoteses_distintas():
    vistos = []

    def gerar(_prompt, sistema=""):
        vistos.append(sistema)
        return _resp(False)

    painel_adversarial(_EV, "achado", gerar=gerar)
    assert len(vistos) == 3
    assert len({s for s in vistos}) == 3, "as três lentes receberam o MESMO prompt"
    assert any("ADMINISTRATIVA" in s for s in vistos)
    assert any("LACUNA DE DADO" in s for s in vistos)
    assert any("DETECTOR errou" in s for s in vistos)


def test_maioria_refuta():
    r = painel_adversarial(_EV, "achado", gerar=_por_lente({
        "ADMINISTRATIVA": _resp(True, "prática usual do setor"),
        "LACUNA DE DADO": _resp(True, "documento não capturado"),
        "DETECTOR errou": _resp(False),
    }))
    assert r["refutada"] is True and r["n_refutaram"] == 2


def test_uma_lente_isolada_NAO_descarta_mas_rebaixa():
    """Discordância entre lentes é informação para quem assina, não empate a resolver em silêncio."""
    r = painel_adversarial(_EV, "achado", gerar=_por_lente({
        "LACUNA DE DADO": _resp(True, "campo vazio na base"),
    }))
    assert r["refutada"] is False and r["rebaixa"] is True


def test_nenhuma_refutacao_deixa_o_achado_intacto():
    r = painel_adversarial(_EV, "achado", gerar=_por_lente({}))
    assert r["refutada"] is False and r["rebaixa"] is False
    assert "sobreviveu" in r["motivo"]


def test_painel_todo_indisponivel_nao_refuta_por_omissao():
    """INDISPONÍVEL ≠ refutado. LLM fora do ar não pode apagar achado do código."""
    def explode(*_a, **_k):
        raise RuntimeError("provedor fora do ar")

    r = painel_adversarial(_EV, "achado", gerar=explode)
    assert r["refutada"] is False and r["n_responderam"] == 0
    assert "indisponível" in r["motivo"]


def test_quorum_e_medido_sobre_quem_RESPONDEU_nao_sobre_as_tres_nominais():
    """Com duas lentes fora do ar, uma refutação isolada não pode virar 'maioria'."""
    def gerar(_prompt, sistema=""):
        if "ADMINISTRATIVA" in sistema:
            return _resp(True, "explicação lícita")
        raise RuntimeError("fora do ar")

    r = painel_adversarial(_EV, "achado", gerar=gerar)
    assert r["n_responderam"] == 1
    assert r["refutada"] is False, "1 de 1 não é maioria de um painel de 3"
    assert r["rebaixa"] is True


def test_resposta_nao_parseavel_nao_conta_como_voto():
    r = painel_adversarial(_EV, "achado", gerar=lambda *_a, **_k: "desculpe")
    assert r["n_responderam"] == 0 and r["refutada"] is False


# ───────────────────────────── integração com o ResultadoDetector ─────────────────────────────

def _res():
    return ResultadoDetector(detector="X1", processo="P-1", status="confirmado", score=0.85,
                             evidencia=_EV)


def test_aplicar_exculpatoria_com_painel_descarta_por_maioria():
    r = aplicar_exculpatoria(_res(), "achado", painel=True, gerar=_por_lente({
        "ADMINISTRATIVA": _resp(True), "LACUNA DE DADO": _resp(True)}))
    assert r.status == "descartado" and r.refutada is True
    assert r.valores["painel_adversarial"]


def test_aplicar_exculpatoria_com_painel_rebaixa_score_com_uma_refutacao():
    r = aplicar_exculpatoria(_res(), "achado", painel=True,
                             gerar=_por_lente({"DETECTOR errou": _resp(True, "artefato conhecido")}))
    assert r.status == "confirmado"
    assert r.score == pytest.approx(0.425), "score deveria cair pela metade"
    assert "sem maioria" in r.motivo_refutacao


def test_painel_e_opt_in_o_padrao_continua_a_lente_unica():
    """3× de inferência não pode virar custo default da triagem em massa."""
    chamadas = []

    def gerar(_prompt, sistema=""):
        chamadas.append(sistema)
        return _resp(False)

    aplicar_exculpatoria(_res(), "achado", gerar=gerar)
    assert len(chamadas) == 1
