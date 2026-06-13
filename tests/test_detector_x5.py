# -*- coding: utf-8 -*-
"""Teste TARGETED do detector X5 · JOGO DE PLANILHA (fase de execução) — spec V2 do dono §X5.

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO (dicts), LLM ausente OU rubrica pré-classificada
injetada (sem rede). Cobre: (a) CONFIRMA forte por correlação direcional (itens caros cresceram, baratos sumiram);
(b) só desequilíbrio inicial SEM execução → no máximo médio; (c) descartado (preços heterogêneos SEM correlação
direcional — itens caros NÃO cresceram); (d) cálculo do DANO em R$; (e) sem itens/referencial → nao_avaliavel.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detector_x5.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS, ResultadoDetector
from compliance_agent.detectores.x5_jogo_planilha import X5JogoDePlanilha, _pearson


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


def _itens_direcionais() -> list[dict]:
    """Planilha desenhada: itens SOBREPRECIFICADOS cresceram, SUBCOTADOS sumiram → correlação positiva forte.
    Referencial = 100 em todos para isolar o desvio no preço."""
    return [
        # caros (desvio +) que cresceram (var_qtd +)
        {"item": "A", "preco_contratado": 150.0, "referencial": 100.0, "quantidade_contratada": 100.0, "quantidade_executada": 200.0},
        {"item": "B", "preco_contratado": 140.0, "referencial": 100.0, "quantidade_contratada": 100.0, "quantidade_executada": 180.0},
        {"item": "C", "preco_contratado": 130.0, "referencial": 100.0, "quantidade_contratada": 100.0, "quantidade_executada": 160.0},
        # baratos (desvio −) que sumiram (var_qtd −)
        {"item": "D", "preco_contratado": 70.0, "referencial": 100.0, "quantidade_contratada": 100.0, "quantidade_executada": 40.0},
        {"item": "E", "preco_contratado": 60.0, "referencial": 100.0, "quantidade_contratada": 100.0, "quantidade_executada": 20.0},
        {"item": "F", "preco_contratado": 80.0, "referencial": 100.0, "quantidade_contratada": 100.0, "quantidade_executada": 50.0},
    ]


# ═══════════════════════════════ (a) CONFIRMA forte — correlação direcional ═══════════════════════════════
def test_x5_confirma_forte_correlacao_direcional():
    """Itens caros cresceram e baratos sumiram → Pearson r alto → forte/crítico."""
    ctx = {"processo": "x5-1", "itens": _itens_direcionais()}
    r = X5JogoDePlanilha().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["tem_execucao"] is True
    assert r.valores["correlacao_pearson"] is not None and r.valores["correlacao_pearson"] >= 0.8
    assert r.valores["n_sobreprecificados"] >= 1 and r.valores["n_subcotados"] >= 1
    assert r.evidencia  # itens caros + coeficiente de correlação


# ═══════════════════════════════ (b) só desequilíbrio inicial, SEM execução → no máximo médio ═══════════════
def test_x5_sem_execucao_no_maximo_medio():
    """Planilha desequilibrada (caros + baratos) mas SEM quantidade_executada → não há correlação → máx médio."""
    itens = [
        {"item": "A", "preco_contratado": 150.0, "referencial": 100.0},
        {"item": "B", "preco_contratado": 140.0, "referencial": 100.0},
        {"item": "D", "preco_contratado": 70.0, "referencial": 100.0},
        {"item": "E", "preco_contratado": 60.0, "referencial": 100.0},
    ]
    r = X5JogoDePlanilha().avaliar({"processo": "x5-2", "itens": itens})
    _valido(r)
    assert r.status == "confirmado"
    assert r.valores["tem_execucao"] is False
    assert r.valores["correlacao_pearson"] is None
    assert r.score <= ANCORAS["medio"]  # desequilíbrio sozinho não passa de 0.6


# ═══════════════════════════════ (c) descartado — heterogêneo SEM correlação direcional ═══════════════════
def test_x5_descartado_heterogeneo_sem_direcao():
    """Preços heterogêneos (caros + baratos) mas itens caros NÃO cresceram (até encolheram): sem correlação
    direcional positiva. Não passa de médio (exculpatória: margens heterogêneas sem desenho)."""
    itens = [
        # caros que NÃO cresceram (até encolheram) — quebra a direção
        {"item": "A", "preco_contratado": 150.0, "referencial": 100.0, "quantidade_contratada": 100.0, "quantidade_executada": 60.0},
        {"item": "B", "preco_contratado": 140.0, "referencial": 100.0, "quantidade_contratada": 100.0, "quantidade_executada": 50.0},
        # baratos que cresceram
        {"item": "D", "preco_contratado": 70.0, "referencial": 100.0, "quantidade_contratada": 100.0, "quantidade_executada": 180.0},
        {"item": "E", "preco_contratado": 60.0, "referencial": 100.0, "quantidade_contratada": 100.0, "quantidade_executada": 200.0},
    ]
    r = X5JogoDePlanilha().avaliar({"processo": "x5-3", "itens": itens})
    _valido(r)
    # correlação NEGATIVA (oposta ao jogo de planilha) → não aciona forte; fica no patamar do desequilíbrio
    assert r.valores["correlacao_pearson"] is not None and r.valores["correlacao_pearson"] < 0.5
    assert r.score <= ANCORAS["medio"]


def test_x5_descartado_sem_desequilibrio():
    """Todos os itens próximos do referencial (sem caros NEM baratos) → descartado (sem coexistência)."""
    itens = [
        {"item": "A", "preco_contratado": 101.0, "referencial": 100.0, "quantidade_contratada": 100.0, "quantidade_executada": 200.0},
        {"item": "B", "preco_contratado": 100.0, "referencial": 100.0, "quantidade_contratada": 100.0, "quantidade_executada": 100.0},
        {"item": "C", "preco_contratado": 99.0, "referencial": 100.0, "quantidade_contratada": 100.0, "quantidade_executada": 50.0},
    ]
    r = X5JogoDePlanilha().avaliar({"processo": "x5-4", "itens": itens})
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


# ═══════════════════════════════ (d) cálculo do DANO em R$ ═══════════════════════════════
def test_x5_dano_em_reais():
    """Dano = Σ (preço_contratado − referencial) × qtd_executada, SÓ nos sobreprecificados.
    Itens caros A,B,C: (150-100)*200 + (140-100)*180 + (130-100)*160 = 10000 + 7200 + 4800 = 22000."""
    ctx = {"processo": "x5-5", "itens": _itens_direcionais()}
    r = X5JogoDePlanilha().avaliar(ctx)
    _valido(r)
    assert r.valores["dano_estimado_reais"] == 22000.0


# ═══════════════════════════════ (e) honestidade — sem itens / sem referencial → nao_avaliavel ═══════════════
def test_x5_sem_itens_nao_avaliavel():
    r = X5JogoDePlanilha().avaliar({"processo": "x5-6", "itens": []})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.score == 0.0
    assert r.valores["n_itens"] == 0


def test_x5_sem_referencial_nao_avaliavel():
    """Itens sem referencial (só preço contratado) → nenhuma linha avaliável → nao_avaliavel (campo ausente ≠ 0)."""
    itens = [
        {"item": "A", "preco_contratado": 150.0},
        {"item": "B", "preco_contratado": 70.0, "referencial": 0},  # referencial 0 é inválido
    ]
    r = X5JogoDePlanilha().avaliar({"processo": "x5-7", "itens": itens})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.valores["n_itens_avaliaveis"] == 0


# ═══════════════════════════════ rubrica subjetiva + helpers ═══════════════════════════════
def test_x5_rubrica_sem_justificativa_agrava():
    """Rubrica 'sem_justificativa' injetada (sem LLM) agrava o achado direcional."""
    ctx = {
        "processo": "x5-8",
        "itens": _itens_direcionais(),
        "_rubrica_justificativa": {"nivel": "sem_justificativa", "trecho": "nenhuma justificativa anexada ao aditivo"},
    }
    r = X5JogoDePlanilha().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.valores["justificativa_variacoes"] == "sem_justificativa"


def test_x5_rubrica_superveniente_nao_salva_correlacao_forte():
    """'superveniente_documentado' NÃO rebaixa quando a correlação direcional é forte (fato novo não explica por que
    justamente os itens caros cresceram)."""
    ctx = {
        "processo": "x5-9",
        "itens": _itens_direcionais(),
        "_rubrica_justificativa": {"nivel": "superveniente_documentado", "trecho": "alteração de projeto por fato novo"},
    }
    r = X5JogoDePlanilha().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]  # correlação forte sobrevive ao documento


def test_x5_pearson_inline():
    """Sanidade da Pearson inline: série perfeitamente correlacionada → r≈1; série constante → None."""
    assert _pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) > 0.999
    assert _pearson([1.0, 1.0, 1.0], [2.0, 4.0, 6.0]) is None
    assert _pearson([1.0], [2.0]) is None
