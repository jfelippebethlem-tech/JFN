# -*- coding: utf-8 -*-
"""Camada determinística (offline) de direcionamento — cláusulas restritivas, cascata e veredito.

Tudo SEM rede e SEM LLM (Gemini desligado §4.1): o sinal precisa aparecer com a IA off.
"""
from __future__ import annotations

import asyncio

from compliance_agent import direcionamento_sinais as DS
from compliance_agent import direcionamento_cerebro as DC

# Edital sintético com vedação-de-somatório + ata com 3 inabilitações pelo MESMO motivo.
_EDITAL = (
    "EDITAL DE PREGÃO ELETRÔNICO Nº 01/2025. Termo de Referência. "
    "Para fins de QUALIFICAÇÃO TÉCNICA exige-se atestado de capacidade técnica. "
    "Não será admitido o somatório de atestados para comprovação da capacidade técnica exigida. "
    "O equipamento deverá ser da marca Alfa, modelo X-200. "
    "A visita técnica será obrigatória e deverá ser realizada pela licitante. " * 6
)
_ATA = (
    "ATA DE JULGAMENTO. A empresa Beta foi INABILITADA por não apresentar atestado de capacidade técnica. "
    "A empresa Gama foi INABILITADA por não apresentar atestado de capacidade técnica. "
    "A empresa Delta foi INABILITADA por não apresentar atestado de capacidade técnica. "
    "A empresa Ômega foi declarada vencedora. "
)


def test_clausula_vedacao_somatorio_verbatim():
    cl = DS.extrair_clausulas_restritivas(_EDITAL)
    tipos = {c["tipo"] for c in cl}
    assert "vedacao_somatorio_atestado" in tipos
    veda = next(c for c in cl if c["tipo"] == "vedacao_somatorio_atestado")
    assert "somat" in veda["trecho"].lower() and len(veda["trecho"]) <= 200
    assert "263" in veda["base"]  # Súmula TCU 263 citada
    assert "marca_modelo" in tipos and "visita_obrigatoria" in tipos


def test_vinculo_previo_e_amostra_de_todos_sumula_272():
    # custo prévio indevido (Súmula TCU 272): vínculo empregatício na proposta + amostra de todos antes do julgamento.
    edital = (
        "EDITAL DE PREGÃO ELETRÔNICO. TERMO DE REFERÊNCIA. QUALIFICAÇÃO TÉCNICA e HABILITAÇÃO. "
        "O profissional deverá possuir vínculo empregatício comprovado por CTPS com a licitante na data "
        "da apresentação da proposta. Será exigida amostra de todos os licitantes antes da fase de habilitação."
    )
    tipos = {c["tipo"] for c in DS.extrair_clausulas_restritivas(edital)}
    assert "vinculo_previo" in tipos
    assert "amostra_previa" in tipos
    bases = {c["tipo"]: c["base"] for c in DS.extrair_clausulas_restritivas(edital)}
    assert "272" in bases["vinculo_previo"] and "272" in bases["amostra_previa"]  # Súmula TCU 272 citada


def test_vinculo_e_amostra_nao_escalam_para_vermelho():
    # garantia do fix: ambas são NÃO-FORTE — sozinhas mantêm grau amarelo, nunca sobem para vermelho
    # (vermelho exige restritiva FORTE + cascata). Sem ata/cascata, só essas duas cláusulas → amarelo.
    edital = (
        "EDITAL DE PREGÃO ELETRÔNICO. TERMO DE REFERÊNCIA. QUALIFICAÇÃO TÉCNICA e HABILITAÇÃO. "
        "O profissional deverá possuir vínculo empregatício comprovado por CTPS com a licitante na data "
        "da apresentação da proposta. Será exigida amostra de todos os licitantes antes da fase de habilitação. "
    ) * 8
    assert "vinculo_previo" not in DS._FORTE and "amostra_previa" not in DS._FORTE
    out = DS.analisar_direcionamento_det(edital)
    assert out["grau_det"] == "amarelo"
    assert out["dados_suficientes"] is True
    assert sum(1 for c in out["clausulas"] if c["tipo"] in DS._FORTE) == 0


def test_vinculo_e_amostra_falso_positivo_credenciamento_cbmerj():
    # falsos-positivos REAIS do edital de credenciamento do CBMERJ (270003): boilerplate contratual de vínculo
    # e cláusula de sanção / amostragem de fiscalização não são exigência restritiva.
    boiler = (
        "EDITAL. HABILITAÇÃO. O presente Contrato não configura vínculo empregatício entre os trabalhadores "
        "ou sócios do CREDENCIADO e o CREDENCIANTE. Constitui infração deixar de apresentar amostra. "
        "Mensalmente os fiscais escolherão aleatoriamente uma amostragem de pacientes."
    )
    tipos = {c["tipo"] for c in DS.extrair_clausulas_restritivas(boiler)}
    assert "vinculo_previo" not in tipos
    assert "amostra_previa" not in tipos


def test_cascata_mesmo_motivo():
    inab = DS.extrair_inabilitacoes(_ATA)
    assert inab["n_inabilitadas"] == 3
    casc = inab["cascata_mesmo_motivo"]
    assert casc["repetido"] is True and casc["n"] == 3
    assert "atestado" in casc["quais"][0]["motivo_trecho"].lower()  # motivo verbatim
    assert inab["vencedor"] is not None  # vencedora detectada


def test_veredito_vermelho():
    out = DS.analisar_direcionamento_det(_EDITAL + "\n\n" + _ATA)
    assert out["grau_det"] == "vermelho"
    assert out["dados_suficientes"] is True
    assert out["cascata"] is True and out["n_clausulas_restritivas"] >= 1
    assert any("cascata" in s for s in out["sinais"])
    assert any("somat" in s.lower() for s in out["sinais"])


def test_dados_insuficientes_honesto():
    out = DS.analisar_direcionamento_det("Despacho de mero expediente. Arquivamento do processo.")
    assert out["grau_det"] == "indeterminado" and out["dados_suficientes"] is False
    assert DS.extrair_clausulas_restritivas("") == []


def test_wired_no_cerebro_sem_llm():
    # avaliar_direcionamento deve anexar sinais_deterministicos MESMO sem chamar LLM (dados insuficientes).
    async def _fake(_):
        raise AssertionError("LLM não deveria ser chamado aqui")
    out = asyncio.run(DC.avaliar_direcionamento("", "", gerar=_fake))
    assert "sinais_deterministicos" in out
    assert out["sinais_deterministicos"]["grau_det"] == "indeterminado"

    # com edital+ata reais, o determinístico fica vermelho e é anexado ao lado do veredito LLM (mockado).
    async def _fake_ok(_):
        return '{"grau":"amarelo","resumo":"x","dados_suficientes":true}'
    out2 = asyncio.run(DC.avaliar_direcionamento(_EDITAL, _ATA, gerar=_fake_ok))
    assert out2["sinais_deterministicos"]["grau_det"] == "vermelho"
    assert out2["grau"] == "amarelo"  # caminho LLM preservado (aditivo, não quebra)
