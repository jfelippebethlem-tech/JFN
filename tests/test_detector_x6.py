# -*- coding: utf-8 -*-
"""Teste TARGETED do detector X6 — ENTREGA FANTASMA / ATESTO DE FACHADA (fase de execução, spec V2 do dono §X6).

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO (dicts), LLM ausente OU rubrica pré-classificada
injetada (sem rede). Cobre: (a) forte por tríade incompleta; (b) forte por atesto contraditório (rubrica);
(c) atesto só genérico → medio (não sobe sozinho); (d) valor fixo mensal com medições idênticas → rebaixado;
(e) roteiro de diligência no resultado de score alto; (f) sem NFs/atestos → nao_avaliavel.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detector_x6.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS, ResultadoDetector
from compliance_agent.detectores.x6_entrega_fantasma import X6EntregaFantasma


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


# ═══════════════════════════════ (a) tríade incompleta → forte ═══════════════════════════════
def test_x6_confirma_triade_incompleta_sem_nf():
    """Pagamento sem NF / sem recebimento → tríade documental INCOMPLETA → forte."""
    ctx = {
        "processo": "x6-1",
        "pagamentos": [
            {"valor": 50000.0, "data": "2024-03-01", "tem_nf": False, "tem_recebimento": True},
            {"valor": 48000.0, "data": "2024-04-01", "tem_nf": True, "tem_recebimento": False},
        ],
        "atestos": [{"texto": "atesto a entrega de 100 notebooks no almoxarifado central", "data": "2024-03-02"}],
    }
    r = X6EntregaFantasma().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["pagamentos_sem_nf"] == 1
    assert r.valores["pagamentos_sem_recebimento"] == 1
    assert r.evidencia


# ═══════════════════════════════ (b) atesto contraditório (rubrica) → forte ═══════════════════════════════
def test_x6_confirma_atesto_contraditorio_rubrica():
    """Rubrica injetada 'contraditorio' (sem rede) → forte; evidência atesto × documento conflitante."""
    ctx = {
        "processo": "x6-2",
        "atestos": [{"texto": "atesto a entrega integral dos equipamentos", "data": "2024-05-01"}],
        "documento_conflitante": "termo de recebimento registra que nenhum equipamento chegou ao almoxarifado",
        "_rubrica_especificidade": {"nivel": "contraditorio", "trecho": "atesto a entrega integral dos equipamentos"},
    }
    r = X6EntregaFantasma().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["especificidade_atesto"] == "contraditorio"
    assert any("contradiz" in e["trecho"] for e in r.evidencia)


# ═══════════════════════════════ (c) atesto só genérico → medio, não sobe ═══════════════════════════════
def test_x6_atesto_so_generico_eh_medio_nao_sobe():
    """Atesto genérico SEM contradição/tríade incompleta → medio (0.6), não sobe sozinho (má prática ≠ prova)."""
    ctx = {
        "processo": "x6-3",
        "pagamentos": [{"valor": 30000.0, "data": "2024-06-01", "tem_nf": True, "tem_recebimento": True}],
        "atestos": [{"texto": "serviços prestados a contento", "data": "2024-06-02"}],
        "_rubrica_especificidade": {"nivel": "generico", "trecho": "serviços prestados a contento"},
    }
    r = X6EntregaFantasma().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["medio"]
    assert r.valores["especificidade_atesto"] == "generico"


def test_x6_generico_fallback_heuristico_sem_llm():
    """Sem rubrica e sem LLM, texto genérico aciona fallback heurístico → medio (não sobe)."""
    ctx = {
        "processo": "x6-3b",
        "pagamentos": [{"valor": 12000.0, "data": "2024-06-10", "tem_nf": True, "tem_recebimento": True}],
        "atestos": [{"texto": "atesto os serviços prestados regularmente, sem ressalvas", "data": "2024-06-11"}],
    }
    r = X6EntregaFantasma().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["medio"]
    assert r.valores["especificidade_atesto"] == "generico"


# ═══════════════════════════════ (d) valor fixo mensal → cadência idêntica rebaixada ═══════════════════════════════
def test_x6_valor_fixo_medicoes_identicas_rebaixado():
    """Locação (valor fixo mensal) com medições IDÊNTICAS legítimas + tríade completa → descartado (exculpa)."""
    ctx = {
        "processo": "x6-4",
        "pagamentos": [{"valor": 8000.0, "data": "2024-01-05", "tem_nf": True, "tem_recebimento": True}],
        "atestos": [{"texto": "atesto a locação mensal de 5 veículos, placas ABC-1234..", "data": "2024-01-06"}],
        "medicoes": [8000.0, 8000.0, 8000.0, 8000.0],
        "tipo_objeto": "locacao",
    }
    r = X6EntregaFantasma().avaliar(ctx)
    _valido(r)
    assert r.valores["valor_fixo_mensal"] is True
    assert r.valores["medicoes_identicas"] is True
    assert r.status == "descartado"
    assert r.score == 0.0


def test_x6_cadencia_identica_sem_valor_fixo_pontua():
    """Mesmas medições idênticas SEM natureza de valor fixo → indício (fraco), não rebaixado."""
    ctx = {
        "processo": "x6-4b",
        "atestos": [{"texto": "atesto execução de serviço de limpeza", "data": "2024-02-01"}],
        "medicoes": [12345.0, 12345.0, 12345.0, 12345.0],
        "tipo_objeto": "servico de limpeza",
    }
    r = X6EntregaFantasma().avaliar(ctx)
    _valido(r)
    assert r.valores["medicoes_identicas"] is True
    assert r.valores["valor_fixo_mensal"] is False
    assert r.score >= ANCORAS["fraco"]


# ═══════════════════════════════ (e) roteiro de diligência em score alto ═══════════════════════════════
def test_x6_gera_roteiro_diligencia_score_alto():
    """Resultado de score alto (tríade incompleta + volume×capacidade) CULMINA em roteiro de diligência física."""
    ctx = {
        "processo": "x6-5",
        "pagamentos": [{"valor": 200000.0, "data": "2024-07-01", "tem_nf": False, "tem_recebimento": False}],
        "atestos": [{"texto": "atesto a entrega de 500 toneladas de asfalto", "data": "2024-07-02"}],
        "volume_contratado": 500,
        "capacidade_fornecedor": {"funcionarios": 0, "frota": 0},
        "fiscais": ["fiscal joao", "fiscal joao", "fiscal joao"],
    }
    r = X6EntregaFantasma().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["diligencia_recomendada"] is True
    roteiro = r.valores["roteiro_diligencia"]
    assert isinstance(roteiro, list) and len(roteiro) >= 3
    assert any("Fotografar" in p for p in roteiro)
    assert r.valores["baixa_rotacao_fiscal"] is True


def test_x6_roteiro_quando_verificavel_em_campo():
    """Rubrica verossimilhança 'verificavel_em_campo' dispara o roteiro mesmo com indício menor."""
    ctx = {
        "processo": "x6-5b",
        "atestos": [{"texto": "atesto reforma da fachada do prédio sede", "data": "2024-08-01"}],
        "medicoes": [10000.0, 10000.0, 10000.0],
        "tipo_objeto": "obra de reforma",
        "_rubrica_verossimilhanca": {"nivel": "verificavel_em_campo", "trecho": "reforma da fachada do prédio sede"},
    }
    r = X6EntregaFantasma().avaliar(ctx)
    _valido(r)
    assert r.valores["verossimilhanca_fisica"] == "verificavel_em_campo"
    assert "roteiro_diligencia" in r.valores
    assert r.valores["diligencia_recomendada"] is True


# ═══════════════════════════════ (f) sem NFs/atestos → nao_avaliavel ═══════════════════════════════
def test_x6_nao_avaliavel_sem_pagamentos_nem_atestos():
    """Sem pagamentos E sem atestos → nao_avaliavel (campo ausente ≠ 0)."""
    r = X6EntregaFantasma().avaliar({"processo": "x6-6", "volume_contratado": 100})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.score == 0.0
    assert "nao_avaliavel" in r.motivo_refutacao


def test_x6_triade_completa_sem_anomalia_descartado():
    """Tríade completa, capacidade compatível, sem cadência anômala → descartado (presunção de regularidade)."""
    ctx = {
        "processo": "x6-7",
        "pagamentos": [{"valor": 15000.0, "data": "2024-09-01", "tem_nf": True, "tem_recebimento": True}],
        "atestos": [{"texto": "atesto entrega de 10 microcomputadores, série 001-010, sala 204", "data": "2024-09-02"}],
        "capacidade_fornecedor": {"funcionarios": 50, "frota": 5},
        "volume_contratado": 10,
    }
    r = X6EntregaFantasma().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0
