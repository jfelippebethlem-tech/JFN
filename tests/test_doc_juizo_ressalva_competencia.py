# -*- coding: utf-8 -*-
"""Guard-rail: escala 3 provada por CLÁUSULA DE COMPETÊNCIA não se sustenta.

A rubrica v3 (2026-08-02) já instruía o modelo a não tratar a ressalva de competência como
esquiva — e ainda assim 3 pareceres saíram escala 3 citando exatamente o disclaimer como prova
(`Dito isto, a presente análise toma por base, exclusivamente, os elementos…`). Prompt não é
contrato: quem garante é o código. A leitura pericial de 14 pareceres marcados assim deu 14
"não sustenta" — o rebaixamento para 2 é a leitura correta (favorável COM ressalva).
"""
import pytest

from compliance_agent.sei import doc_juizo


@pytest.mark.parametrize("trecho", [
    "Dito isto, a presente análise toma por base, exclusivamente, os elementos constantes dos autos",
    "não é função do órgão jurídico atestar a vantajosidade ou economicidade do que lhe for submetido",
    "não lhe competindo, pois, eventual análise acerca da conveniência e/ou oportunidade",
    "De igual forma, descabe ao órgão de assessoramento jurídico adentrar no exame do mérito administrativo",
    "O presente parecer não adentra questões técnicas relacionadas às obrigações",
])
def test_reconhece_as_clausulas_de_competencia(trecho):
    assert doc_juizo.ressalva_de_competencia(trecho)


@pytest.mark.parametrize("trecho", [
    "por ora, a questão suscitada não se encontra em condições de ser analisada conclusivamente",
    "Aprovo a Nota de Autorização de Despesa, emitida em favor da empresa",
    "devolvo o processo à origem para que o setor competente decida",
    "",
    None,
])
def test_nao_confunde_esquiva_real_nem_texto_qualquer(trecho):
    assert not doc_juizo.ressalva_de_competencia(trecho)


def test_voto_escala3_por_clausula_de_competencia_e_rebaixado_com_aviso(monkeypatch):
    texto = ("PARECER 1893/2024. Dito isto, a presente análise toma por base, exclusivamente, "
             "os elementos constantes dos autos. Recomenda-se juntar a dotação orçamentária.")
    resposta = ('{"escala": 3, "trecho_literal": "Dito isto, a presente análise toma por base, '
                'exclusivamente, os elementos constantes dos autos", "justificativa_curta": "não conclui"}')
    v = doc_juizo._um_voto(lambda *a, **k: resposta, "prompt", texto)
    assert v["escala"] == 2, "cláusula de competência não pode sustentar escala 3"
    assert "ressalva de competência" in (v.get("aviso") or "")


def test_esquiva_real_continua_escala3(monkeypatch):
    texto = ("PARECER. Sendo assim, entende-se que, por ora, a questão suscitada não se encontra "
             "em condições de ser analisada conclusivamente por esta Assessoria.")
    resposta = ('{"escala": 3, "trecho_literal": "por ora, a questão suscitada não se encontra em '
                'condições de ser analisada conclusivamente", "justificativa_curta": "devolve sem decidir"}')
    v = doc_juizo._um_voto(lambda *a, **k: resposta, "prompt", texto)
    assert v["escala"] == 3, "o guard-rail não pode engolir esquiva verdadeira"
