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


# ───────────────────── novas famílias (expansão 2026-07-16) ─────────────────────
# Cada regra nova: 1 positivo verbatim + 1 guarda de falso-positivo em prosa administrativa.

_CTX = ("EDITAL DE PREGÃO ELETRÔNICO. Termo de Referência. QUALIFICAÇÃO TÉCNICA: exige-se atestado "
        "de capacidade técnica e documentos de habilitação conforme a proposta. " * 4)


def _tipos(texto):
    return {c["tipo"] for c in DS.extrair_clausulas_restritivas(texto)}


def test_vedacao_consorcio_dispara_e_prosa_nao():
    assert "vedacao_consorcio" in _tipos(
        _CTX + "Não será admitida a participação de empresas reunidas em consórcio.")
    assert "vedacao_consorcio" not in _tipos(
        _CTX + "O consórcio intermunicipal de saúde firmou convênio com o Estado.")


def test_indices_contabeis_desproporcional_dispara_e_usual_nao():
    assert "indices_contabeis" in _tipos(
        _CTX + "Índice de Liquidez Geral igual ou superior a 2,0, comprovado pelo balanço.")
    # índice usual (1,0) NÃO é restritivo — não dispara
    assert "indices_contabeis" not in _tipos(
        _CTX + "Índice de Liquidez Geral igual ou superior a 1,0, comprovado pelo balanço.")


def test_atestado_percentual_alto_dispara_e_50_nao():
    assert "atestado_percentual_alto" in _tipos(
        _CTX + "O atestado deverá comprovar execução de no mínimo 70% do quantitativo do objeto.")
    assert "atestado_percentual_alto" not in _tipos(
        _CTX + "O atestado deverá comprovar execução de no mínimo 50% do quantitativo do objeto.")


def test_registro_regional_crea_dispara():
    assert "registro_regional" in _tipos(
        _CTX + "Registro ou inscrição da empresa no CREA do Estado do Rio de Janeiro, como condição de habilitação.")


def test_cadastro_antecedencia_dispara_e_sicaf_normal_nao():
    assert "cadastro_antecedencia" in _tipos(
        _CTX + "O credenciamento deverá ser efetuado com antecedência mínima de 3 dias úteis da sessão pública.")
    assert "cadastro_antecedencia" not in _tipos(
        _CTX + "O credenciamento no SICAF é gratuito e pode ser feito a qualquer tempo.")


def test_filiacao_entidade_dispara():
    assert "filiacao_entidade" in _tipos(
        _CTX + "A licitante deverá estar filiada ao sindicato da categoria, apresentando comprovação.")


def test_distancia_maxima_usina_dispara():
    assert "distancia_maxima" in _tipos(
        _CTX + "A usina de asfalto deverá situar-se a uma distância máxima de 40 km do canteiro de obras.")


def test_prazo_exiguo_dispara_e_prazo_legal_nao():
    assert "prazo_exiguo" in _tipos(
        _CTX + "A entrega das propostas deverá ocorrer no prazo de 8 horas contadas da publicação.")
    assert "prazo_exiguo" not in _tipos(
        _CTX + "A entrega das propostas ocorrerá no prazo de 8 dias úteis, na forma da lei.")


def test_sinais_certame_licitante_unico_e_desconto_irrisorio():
    ata = ("ATA DA SESSÃO PÚBLICA. Compareceu apenas uma licitante interessada. A empresa foi inabilitada e "
           "depois habilitada em diligência. O valor estimado da contratação é de R$ 1.000.000,00. "
           "Foi declarada vencedora com proposta homologada no valor de R$ 998.000,00. "
           "As demais empresas foram desclassificadas por não apresentar atestado. " * 3)
    r = DS.sinais_de_certame(ata)
    assert r["licitante_unico"] is True
    assert r["desconto"] and r["desconto"]["desconto_pct"] < 1.0
    det = DS.analisar_direcionamento_det(ata)
    assert det["grau_det"] in ("amarelo", "vermelho")
    assert any("LICITANTE ÚNICO" in s for s in det["sinais"])
    assert any("desconto irrisório" in s for s in det["sinais"])


def test_sinais_certame_desconto_saudavel_nao_dispara():
    ata = ("ATA DA SESSÃO. O valor estimado da contratação é de R$ 1.000.000,00. Melhor proposta "
           "homologada no valor de R$ 780.000,00 após disputa de lances entre nove licitantes.")
    r = DS.sinais_de_certame(ata)
    assert r["desconto"] is None
