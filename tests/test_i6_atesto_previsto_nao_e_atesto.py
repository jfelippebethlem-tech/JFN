# -*- coding: utf-8 -*-
"""A palavra "atesto" numa cláusula de PAGAMENTO não é um atesto de execução.

Ela aparece no termo de referência de praticamente todo contrato — *"o pagamento será mensal,
mediante atesto a ser realizado por agentes da Comissão Fiscalizadora"* —, e isso é a **previsão**
de que haverá atesto, não o ato.

Medido em 2026-08-05 nos SEI-420001/004224/2024 e /004223/2024, nºs 6 e 7 da fila do fiscal: o I6
acusava *"o objeto contratado é de 30 veículos e o atesto de execução fala em 3"*. O "3" saía do
próprio TR, da distribuição interna do objeto — *"21 (vinte e um) veículos para as Operações
Presente; e 03 (três) veículos para a Operação Barreira Fiscal"* —, e o documento entrou como
"atesto" pela cláusula de pagamento. Total contra parcela, num papel que não atesta nada.

Mesma doutrina da família 19 do catálogo e do `_RX_ENTREGA_AFIRMADA`: **o modo verbal decide**.
"atesto A ser realizado" é infinitivo; por isso o complemento aceito é `que` ou a fórmula de
praxe, nunca um artigo solto — foi o artigo que deixou a cláusula passar na primeira tentativa
desta correção.
"""
from __future__ import annotations

import pytest

from compliance_agent.sei.instrumento_assinatura import _RE_ATESTO


@pytest.mark.parametrize("texto", [
    "O pagamento será mensal, mediante e atesto a ser realizado por agentes da Comissão "
    "Fiscalizadora do Contrato.",
    "Caberá ao fiscal o atesto da nota fiscal.",
    "o atesto será feito em até 5 dias úteis",
])
def test_atesto_apenas_previsto_nao_dispara(texto):
    assert _RE_ATESTO.search(texto) is None


@pytest.mark.parametrize("texto", [
    "ATESTAMOS que os serviços foram prestados a contento no período.",
    "Atesto que a prestação de serviço foi executada pela contratada conforme o pactuado.",
    "os serviços foram executados pela contratada a contento",
    "Atesto, para os devidos fins, a boa execução dos serviços.",
    "a qualidade da prestação foi satisfatória durante toda a vigência",
])
def test_atesto_afirmado_continua_valendo(texto):
    """A correção não pode desarmar o I6 verdadeiro — o do SEI-270131/000548/2023, onde o objeto é
    de 3 aeronaves e o atesto fala em 4."""
    assert _RE_ATESTO.search(texto) is not None


# ── o atesto não pode ser o próprio instrumento (2026-08-05) ──────────────────

def test_o_contrato_nao_atesta_a_si_mesmo():
    """Todo contrato traz, na cláusula de pagamento, *"considera-se adimplemento o cumprimento da
    prestação com a entrega do objeto, devidamente **atestado pelo(s) agente(s) competente(s)**"* —
    a regra do que o atesto será, não um atesto.

    Com o instrumento dos dois lados, o I6 comparava o TOTAL contratado com uma SUB-ALOCAÇÃO do
    mesmo contrato: no SEI-420001/004224/2024, *"30 (trinta) veículos tipo van"* contra *"03 (três)
    VEÍCULOS TIPO VAN"* da Operação Barreira Fiscal — a distribuição interna dos mesmos 30.
    """
    from compliance_agent.sei import instrumento_assinatura as IA

    contrato = ("CLÁUSULA PRIMEIRA — DO OBJETO. Constitui objeto a locação de 30 (trinta) "
                "veículos tipo van. PARÁGRAFO QUINTO — Considera-se adimplemento o cumprimento da "
                "prestação com a entrega do objeto, devidamente atestado pelo(s) agente(s) "
                "competente(s). A distribuição prevê 3 (três) veículos para a Barreira Fiscal.")
    r = IA.quantitativo_divergente([{"ref": "C", "tipo": "contrato", "texto": contrato}])
    assert r["achado"] is False


def test_atesto_em_documento_SEPARADO_continua_valendo():
    from compliance_agent.sei import instrumento_assinatura as IA

    docs = [{"ref": "C", "tipo": "contrato",
             "texto": "CLÁUSULA PRIMEIRA — DO OBJETO. Constitui objeto a locação de 30 (trinta) "
                      "veículos."},
            {"ref": "A", "tipo": "outro",
             "texto": "ATESTO a boa execução dos serviços referentes a 3 (três) veículos."}]
    r = IA.quantitativo_divergente(docs)
    assert r["achado"] is True and r["objeto"] == 30 and r["atesto"] == 3
