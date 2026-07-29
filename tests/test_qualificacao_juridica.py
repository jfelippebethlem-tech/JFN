# -*- coding: utf-8 -*-
"""A seção que leva o achado até a peça — e que precisa resistir a ser atacada.

Um dossiê que para no achado empurra a decisão jurídica para o leitor e convida ao salto: chamar
de improbidade o que a Lei 14.230/2021 não alcança. Esta seção fecha a distância, e três dos seus
blocos existem por exigência legal expressa, não por elegância:

  · a indicação das CONSEQUÊNCIAS da invalidação (LINDB art. 21; Lei 8.429 art. 17-C, II);
  · a consideração dos OBSTÁCULOS REAIS do gestor (LINDB art. 22; art. 17-C, III);
  · a ressalva de que os elementos NÃO PODEM SER PRESUMIDOS (art. 17-C, I).

Peça de controle externo que ignora os dois primeiros é atacável na origem — e é por isso que
registrá-los fortalece a representação em vez de enfraquecê-la.
"""
from __future__ import annotations

from compliance_agent.reporting.qualificacao_juridica import (
    qualificar,
    render_html,
    secao,
)


# ───────────────────────────── conteúdo ───────────────────────────────────────────────────────

def test_traz_os_regimes_com_dispositivo_e_orgao():
    q = qualificar("especificacao_dirigida")
    assert q["mapeado"] is True and q["regimes"]
    for r in q["regimes"]:
        assert r["dispositivo"] and r["orgao_competente"]


def test_o_que_falta_e_texto_acionavel_nao_jargao():
    """O checklist vira pedido de diligência — 'dolo' sozinho não orienta ninguém."""
    q = qualificar("fracionamento_despesa", provas_disponiveis={"conduta"})
    assert q["o_que_falta"]
    assert any(len(x) > 30 for x in q["o_que_falta"])


def test_vicio_nao_mapeado_declara_a_lacuna_sem_fingir():
    q = qualificar("vicio_inexistente")
    assert q["mapeado"] is False
    html = render_html(q)
    assert "não está mapeado" in html
    assert "não significa ausência de enquadramento" in html


# ───────────────────────── LINDB art. 21 — consequências ──────────────────────────────────────

def test_consequencias_citam_o_fundamento_e_o_art_17_C():
    q = qualificar("aditivo_excessivo", medida="anulacao_contrato")
    c = q["consequencias"]
    assert "art. 21" in c["fundamento"] and "17-C" in c["fundamento"]
    assert c["itens"], "medida conhecida deve trazer consequências típicas"


def test_consequencias_avisam_que_generico_nao_cumpre_o_artigo():
    """Enunciar consequência de forma genérica é o modo mais comum de descumprir o art. 21."""
    q = qualificar("aditivo_excessivo", medida="anulacao_contrato")
    assert "genérica" in q["consequencias"]["aviso"]


def test_sem_medida_definida_a_secao_diz_isso_em_vez_de_inventar():
    q = qualificar("aditivo_excessivo")
    assert q["consequencias"]["itens"] == []
    assert "não definida" in render_html(q)


# ───────────────────────── LINDB art. 22 — obstáculos do gestor ───────────────────────────────

def test_obstaculos_sao_especificos_do_vicio_quando_ha():
    q = qualificar("emergencia_fabricada")
    itens = " ".join(q["obstaculos_do_gestor"]["itens"])
    assert "serviço essencial" in itens


def test_obstaculos_padrao_aparecem_mesmo_sem_lista_especifica():
    q = qualificar("carona_abusiva")
    assert q["obstaculos_do_gestor"]["itens"]


def test_o_aviso_explica_que_registrar_obstaculo_FORTALECE_a_peca():
    q = qualificar("emergencia_fabricada")
    assert "não enfraquece" in q["obstaculos_do_gestor"]["aviso"]


# ───────────────────────── standard e rebaixamento ────────────────────────────────────────────

def test_standard_rebaixa_a_peca_quando_a_prova_nao_alcanca():
    q = qualificar("especificacao_dirigida", grau_evidencia="C",
                   peca_recomendada="representacao")
    assert q["standard"]["rebaixada"] is True and q["standard"]["peca"] == "diligencia"


def test_standard_nao_rebaixa_com_evidencia_forte():
    q = qualificar("especificacao_dirigida", grau_evidencia="B",
                   peca_recomendada="representacao")
    assert q["standard"]["rebaixada"] is False


def test_sem_grau_informado_a_secao_nao_afirma_standard():
    q = qualificar("especificacao_dirigida")
    assert q["standard"] is None


# ───────────────────────── contrato de renderização ───────────────────────────────────────────

def test_secao_sai_no_formato_do_render_html_da_casa():
    s = secao("aditivo_excessivo", medida="glosa_ressarcimento", grau_evidencia="A",
              familias_independentes=2, peca_recomendada="representacao")
    assert set(s) >= {"titulo", "html"}
    assert s["titulo"] and s["html"]


def test_a_secao_atravessa_o_render_html_sem_perder_conteudo():
    from compliance_agent.reporting.render_html import render_html as render_relatorio

    s = secao("fracionamento_despesa", provas_disponiveis={"conduta"},
              medida="determinacao")
    saida = render_relatorio({"titulo": "t", "secoes": [s]})
    assert "Hipóteses de enquadramento" in saida
    assert "Obstáculos e dificuldades reais do gestor" in saida


def test_html_nao_afirma_tipificacao():
    """A seção qualifica hipóteses; quem tipifica é o órgão competente."""
    html = render_html(qualificar("cartel_rodizio", provas_disponiveis={"ato_lesivo"}))
    assert "hipót" in html.lower() or "Hipóteses" in html
    assert "17-C" in html or "presumidos" in html


def test_neutralidade_da_casa_aceita_a_secao():
    """Todo entregável passa pelo gate — a seção não pode citar JFN, Lex nem caminho de arquivo."""
    from compliance_agent.reporting.neutralidade import garantir_neutro

    html = render_html(qualificar("especificacao_dirigida", grau_evidencia="C",
                                  peca_recomendada="representacao"))
    garantir_neutro(html)   # levanta AssertionError se houver termo interno
