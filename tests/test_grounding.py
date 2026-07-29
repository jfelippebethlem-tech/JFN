# -*- coding: utf-8 -*-
"""Âncora de citação: o trecho existe MESMO na fonte, ou o achado cai.

O sistema inteiro pede citação literal ao LLM — `direcionamento_cerebro`, `narrativa_certame`,
`parecer_cumprimento`, `enxame/lentes`, `detectores/base`. Só que, em quase todos, a verificação
é a PRESENÇA de uma string não vazia: qualquer texto inventado passa como "trecho literal". O
único lugar do repositório que confere de verdade é `editais/motivo_inabilitacao.py`, com um
`trecho[:40] in motivo` — e mesmo esse quebra no mundo real, porque o texto vem de OCR de PDF do
SEI, onde a mesma frase aparece com hifenização de fim de linha, espaços duplos, aspas curvas e
acentuação inconsistente.

Este módulo é aquela verificação, feita para o texto que a casa realmente tem. É a diferença
entre grounding DECLARADO e grounding CONFERIDO.
"""
from __future__ import annotations

import pytest

from compliance_agent.nucleo.grounding import ancorar, normalizar

_FONTE = (
    "Constitui exigência do edital a apresentação de atestado de capacidade técnica "
    "registrado no CREA, com quantitativo mínimo de 80% do objeto licitado, vedado o "
    "somatório de atestados."
)


# ───────────────────────────── casos triviais ─────────────────────────────────────────────────

def test_trecho_identico_ancora():
    r = ancorar("atestado de capacidade técnica registrado no CREA", _FONTE)
    assert r["ancorado"] is True
    assert r["similaridade"] == pytest.approx(1.0)
    assert r["offset"] >= 0


def test_trecho_inventado_nao_ancora():
    r = ancorar("condenação por improbidade administrativa em 2019", _FONTE)
    assert r["ancorado"] is False


def test_fonte_vazia_nao_ancora_nada():
    assert ancorar("qualquer coisa", "")["ancorado"] is False
    assert ancorar("qualquer coisa", None)["ancorado"] is False


def test_trecho_vazio_nao_ancora():
    """Citação vazia é ausência de citação — jamais 'ancorada por vacuidade'."""
    for vazio in ("", "   ", None):
        assert ancorar(vazio, _FONTE)["ancorado"] is False


def test_trecho_curto_demais_nao_ancora():
    """"de" casa com quase qualquer texto — não é âncora, é ruído."""
    assert ancorar("de", _FONTE)["ancorado"] is False
    assert ancorar("no CREA", _FONTE)["ancorado"] is False


# ───────────────────────────── o texto real do SEI ────────────────────────────────────────────

def test_hifenizacao_de_fim_de_linha_do_ocr():
    """PDF quebra a palavra: 'capaci-\\ndade'. O LLM cita a palavra inteira, e está certo."""
    fonte = "atestado de capaci-\ndade técnica registrado no CREA"
    assert ancorar("atestado de capacidade técnica registrado", fonte)["ancorado"] is True


def test_espacos_multiplos_e_quebras_de_linha():
    fonte = "atestado   de\n\n capacidade    técnica\tregistrado no CREA"
    assert ancorar("atestado de capacidade técnica registrado no CREA", fonte)["ancorado"] is True


def test_acentuacao_perdida_no_ocr():
    """'tecnica' sem acento é o caso mais comum de OCR ruim — não pode derrubar o achado."""
    fonte = "atestado de capacidade tecnica registrado no CREA"
    assert ancorar("atestado de capacidade técnica registrado no CREA", fonte)["ancorado"] is True


def test_aspas_curvas_e_travessao():
    fonte = 'o edital exige “atestado de capacidade técnica” — com registro no CREA'
    assert ancorar('"atestado de capacidade técnica" - com registro', fonte)["ancorado"] is True


def test_caixa_diferente():
    fonte = "ATESTADO DE CAPACIDADE TÉCNICA REGISTRADO NO CREA"
    assert ancorar("atestado de capacidade técnica registrado", fonte)["ancorado"] is True


def test_normalizar_e_idempotente():
    assert normalizar(normalizar(_FONTE)) == normalizar(_FONTE)


# ───────────────────────────── o limite entre tolerar e inventar ──────────────────────────────

def test_uma_palavra_trocada_ainda_ancora():
    """Modelo às vezes troca uma preposição ao copiar. Isso é cópia, não invenção."""
    r = ancorar("atestado de capacidade técnica registrada no CREA", _FONTE)
    assert r["ancorado"] is True
    assert r["similaridade"] < 1.0


def test_frase_reescrita_com_as_mesmas_palavras_chave_nao_ancora():
    """Paráfrase NÃO é citação literal — é o caso que o gate existe para pegar."""
    r = ancorar("o edital pede que a empresa comprove capacidade junto ao CREA", _FONTE)
    assert r["ancorado"] is False, f"paráfrase ancorou com similaridade {r['similaridade']:.2f}"


def test_trecho_maior_que_a_fonte_nao_ancora():
    assert ancorar(_FONTE + " e mais um monte de coisa inventada", "só isto")["ancorado"] is False


def test_limiar_e_ajustavel_e_declarado():
    frouxo = ancorar("o edital pede capacidade junto ao CREA", _FONTE, limiar=0.30)
    assert frouxo["limiar"] == pytest.approx(0.30)
    assert "similaridade" in frouxo


# ───────────────────────────── contrato de saída ──────────────────────────────────────────────

def test_saida_traz_o_trecho_como_aparece_na_fonte():
    """Para a peça, vale o texto DA FONTE, não o que o modelo digitou."""
    r = ancorar("atestado de capacidade tecnica", _FONTE)
    assert r["ancorado"] is True
    assert "técnica" in r["trecho_na_fonte"], r["trecho_na_fonte"]


def test_offset_aponta_para_o_lugar_certo():
    r = ancorar("vedado o somatório de atestados", _FONTE)
    assert r["ancorado"] is True
    assert _FONTE[r["offset"]:].lower().startswith("vedado")


def test_nunca_levanta_com_entrada_estranha():
    for lixo in (123, [], {}, object()):
        assert ancorar(lixo, _FONTE)["ancorado"] is False
        assert ancorar("texto", lixo)["ancorado"] is False
