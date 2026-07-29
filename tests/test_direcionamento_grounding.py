# -*- coding: utf-8 -*-
"""Grounding CONFERIDO no veredito de direcionamento.

O `_SYS` do `direcionamento_cerebro` manda, em maiúsculas: "CADA achado DEVE citar o TRECHO
literal que o sustenta; sem trecho, não afirme". A exigência estava no prompt e em lugar nenhum
no código — qualquer string em `exigencias_restritivas[].trecho` era aceita como citação literal,
inclusive uma frase que o edital nunca teve. É o achado mais grave que o sistema produz (grau
vermelho de direcionamento vira representação) e era o menos verificado.
"""
from __future__ import annotations

import json

import pytest

from compliance_agent.direcionamento_cerebro import avaliar_sync

# O `avaliar_direcionamento` só aciona a IA quando o texto de fato PARECE peça licitatória
# (>1500 caracteres e marcadores de habilitação/qualificação) ou quando há ata — guard que existe
# para não "analisar direcionamento" num menu do SEI. O fixture precisa passar por esse portão,
# senão o teste mede o guard e não o grounding.
_EDITAL = (
    "EDITAL DE PREGÃO ELETRÔNICO Nº 015/2024\n"
    "1. DO OBJETO. Contratação de empresa especializada na prestação de serviços continuados de "
    "manutenção predial preventiva e corretiva, com fornecimento de materiais e mão de obra.\n"
    "2. DA PARTICIPAÇÃO. Poderão participar do certame os interessados cujo ramo de atividade "
    "seja compatível com o objeto desta licitação e que atendam às condições de habilitação.\n"
    "3. DA QUALIFICAÇÃO TÉCNICA. Para fins de qualificação técnico-operacional, a licitante "
    "deverá apresentar atestado de capacidade técnica registrado no CREA com quantitativo "
    "mínimo de 80% do objeto, vedado o somatório de atestados.\n"
    "4. DA QUALIFICAÇÃO ECONÔMICO-FINANCEIRA. Capital social integralizado equivalente a 10% do "
    "valor estimado da contratação, comprovado na forma da lei, além de certidão negativa de "
    "falência expedida nos últimos 90 dias.\n"
    "5. DA HABILITAÇÃO JURÍDICA. Ato constitutivo, estatuto ou contrato social em vigor, "
    "devidamente registrado, acompanhado de todas as alterações ou da consolidação respectiva.\n"
    "6. DA PROPOSTA. A proposta deverá conter planilha de composição de custos e formação de "
    "preços, com detalhamento dos encargos sociais e trabalhistas incidentes.\n"
    "7. DO JULGAMENTO. O critério de julgamento será o de menor preço global, observado o termo "
    "de referência anexo a este edital e as demais condições nele estabelecidas.\n"
    "8. DA VISITA TÉCNICA. A visita técnica ao local dos serviços é obrigatória e deverá ser "
    "agendada com antecedência mínima de 48 horas junto à fiscalização do contrato.\n"
    "9. DAS SANÇÕES. O descumprimento das obrigações assumidas sujeitará a contratada às "
    "penalidades previstas na legislação de regência, assegurados o contraditório e a ampla "
    "defesa, na forma do instrumento contratual e do termo de referência.\n"
    "10. DOS RECURSOS. Declarada a vencedora, qualquer licitante poderá manifestar, de forma "
    "motivada, a intenção de recorrer, em campo próprio do sistema eletrônico.\n"
)
_ATA = ("ATA DA SESSÃO PÚBLICA. Foram inabilitadas 7 das 8 licitantes por ausência de atestado "
        "no quantitativo exigido no item 3 do edital. A licitante remanescente foi declarada "
        "vencedora pelo valor de sua proposta inicial, sem apresentação de lances.")


def _llm(payload):
    async def gerar(_messages):
        return json.dumps(payload, ensure_ascii=False)
    return gerar


def test_exigencia_com_trecho_inventado_e_descartada():
    r = avaliar_sync(_EDITAL, _ATA, gerar=_llm({
        "grau": "vermelho", "raciocinio": "x", "dados_suficientes": True,
        "exigencias_restritivas": [
            {"exigencia": "atestado", "trecho": "vedado o somatório de atestados"},
            {"exigencia": "inventada", "trecho": "o gestor admitiu ter favorecido a empresa"},
        ], "cascata": []}))
    trechos = [e["trecho"] for e in r["exigencias_restritivas"]]
    assert "vedado o somatório de atestados" in trechos
    assert not any("gestor admitiu" in t for t in trechos), "citação inventada sobreviveu"
    assert r["grounding"]["descartados"] == 1


def test_achado_sem_nenhuma_citacao_ancorada_nao_sustenta_grau_vermelho():
    """Se TODA citação é inventada, o veredito não pode continuar vermelho."""
    r = avaliar_sync(_EDITAL, _ATA, gerar=_llm({
        "grau": "vermelho", "raciocinio": "x", "dados_suficientes": True,
        "exigencias_restritivas": [{"exigencia": "a", "trecho": "frase que nunca existiu no edital"}],
        "cascata": []}))
    assert r["grau"] != "vermelho", f"grau manteve-se {r['grau']} sem nenhuma âncora"
    assert r["grounding"]["taxa_alucinacao"] == 1.0


def test_cascata_tambem_e_conferida():
    r = avaliar_sync(_EDITAL, _ATA, gerar=_llm({
        "grau": "amarelo", "raciocinio": "x", "dados_suficientes": True,
        "exigencias_restritivas": [],
        "cascata": [{"motivo": "m", "trecho": "sete licitantes foram desclassificadas por preço"}]}))
    assert r["cascata"] == []
    assert r["grounding"]["descartados"] == 1


def test_veredito_limpo_nao_ganha_ruido():
    r = avaliar_sync(_EDITAL, _ATA, gerar=_llm({
        "grau": "amarelo", "raciocinio": "x", "dados_suficientes": True,
        "exigencias_restritivas": [{"exigencia": "a", "trecho": "quantitativo mínimo de 80% do objeto"}],
        "cascata": []}))
    assert len(r["exigencias_restritivas"]) == 1
    assert r["grounding"]["descartados"] == 0
    assert r["grounding"]["taxa_alucinacao"] == 0.0


def test_llm_que_nao_devolve_listas_nao_quebra():
    r = avaliar_sync(_EDITAL, _ATA, gerar=_llm({"grau": "verde", "dados_suficientes": True}))
    assert r["grau"] in {"verde", "amarelo", "vermelho", "nao_aplicavel"}
    assert "grounding" in r


def test_llm_todo_descartado_com_deterministico_verde_NAO_vira_verde():
    """O falso conforto que a casa proíbe: 'verde' sem análise interpretativa nenhuma.

    Quando toda citação do LLM é inventada, a camada subjetiva não produziu juízo utilizável. Se
    o determinístico estiver limpo, a fusão devolveria 'verde' — e o caso sairia como REGULAR
    quando na verdade não foi analisado. É o mesmo raciocínio do LLM offline, já implementado em
    `avaliar_direcionamento`: ausência de red flag ≠ regularidade.
    """
    edital_limpo = _EDITAL.replace(
        "vedado o somatório de atestados", "admitido o somatório de atestados").replace(
        "A visita técnica ao local dos serviços é obrigatória", "A visita técnica é facultativa")
    r = avaliar_sync(edital_limpo, "", gerar=_llm({
        "grau": "vermelho", "raciocinio": "x", "dados_suficientes": True,
        "exigencias_restritivas": [{"exigencia": "a", "trecho": "frase que nunca existiu"}],
        "cascata": []}))
    assert r["grau"] != "verde", "veredito de regularidade sem análise interpretativa"
    assert r["grounding"]["llm_descartado"] is True


def test_item_sem_campo_trecho_e_descartado():
    """Item sem citação nenhuma é violação do schema do `_SYS`, que exige `trecho` por achado.

    Descartar é a mesma regra de ouro já aplicada em `detectores/base.avaliar_rubrica`: sem
    citação literal, não pontua. Fica explícito aqui para que o comportamento seja intencional,
    e não efeito colateral de o filtro tratar `None` como não-ancorado.
    """
    r = avaliar_sync(_EDITAL, _ATA, gerar=_llm({
        "grau": "amarelo", "raciocinio": "x", "dados_suficientes": True,
        "exigencias_restritivas": [{"exigencia": "a", "trecho": "quantitativo mínimo de 80%"}],
        "cascata": [{"licitante": "EMP A", "situacao": "desclassificado"}]}))
    assert r["cascata"] == []
    assert r["grounding"]["descartados"] == 1
