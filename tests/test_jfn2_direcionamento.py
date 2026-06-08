# -*- coding: utf-8 -*-
"""Cérebro de direcionamento — pré-sinais, extração de trechos relevantes, parse e guardrails."""
from __future__ import annotations

import asyncio

from compliance_agent import direcionamento_cerebro as DC


def test_presinais_conta_cascata():
    sig = DC.presinais("Foi DESCLASSIFICADA a proposta; empresa INABILITADA por atestado. Recurso negado." * 40)
    assert sig["n_desclassificacoes"] >= 1 and sig["mencoes_atestado"] >= 1 and sig["tem_ata"] is True
    assert DC.presinais("")["tem_ata"] is False


def test_trechos_relevantes_pega_secao_profunda():
    # 'atestado' está bem além dos primeiros chars → a extração por keyword deve capturá-lo
    texto = ("boilerplate " * 2000) + " exige-se ATESTADO de capacidade tecnica especifico " + ("rodape " * 500)
    tr = DC._trechos_relevantes(texto, DC._KW_EDITAL, 2000)
    assert "atestado" in tr.lower() and len(tr) <= 2200


def test_parse_json_tira_cercas():
    assert DC._parse_json('```json\n{"grau":"verde"}\n```') == {"grau": "verde"}
    assert DC._parse_json('lixo {"grau":"amarelo","x":1} fim')["grau"] == "amarelo"
    assert DC._parse_json("sem json") is None


def test_dados_insuficientes_nao_chama_llm():
    # sem ata e sem edital com conteúdo → grau verde honesto, sem tocar no LLM
    chamou = {"n": 0}
    async def _fake(_):
        chamou["n"] += 1
        return "{}"
    out = asyncio.run(DC.avaliar_direcionamento("", "", gerar=_fake))
    assert out["grau"] == "verde" and out["dados_suficientes"] is False and chamou["n"] == 0


def test_avaliar_parseia_resposta_llm():
    edital = "Exige-se atestado de capacidade tecnica. " * 80  # >1500 chars
    async def _fake(_):
        return '{"grau":"amarelo","resumo":"indício","exigencias_restritivas":[{"trecho":"atestado X","por_que_restringe":"muito especifico","jurisprudencia":"Súmula TCU 263"}],"dados_suficientes":true}'
    out = asyncio.run(DC.avaliar_direcionamento(edital, "", gerar=_fake))
    assert out["grau"] == "amarelo" and out["exigencias_restritivas"][0]["jurisprudencia"] == "Súmula TCU 263"
    assert "presinais" in out and out["ressalva"]


def test_llm_indisponivel_e_honesto():
    async def _boom(_):
        raise RuntimeError("offline")
    out = asyncio.run(DC.avaliar_direcionamento("edital " * 400, "", gerar=_boom))
    assert out["grau"] == "indisponivel" and out["dados_suficientes"] is False
