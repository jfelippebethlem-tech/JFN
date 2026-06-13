# -*- coding: utf-8 -*-
"""Teste TARGETED do detector da FASE DE EXECUÇÃO X3 (execução financeira anômala) — spec V2 do dono, §X3.

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO (dicts), LLM ausente OU rubrica pré-classificada
injetada (sem rede). Cobre: (a) pagamento ANTES do atesto → forte; (b) ≥40% em dezembro + sem cronograma →
confirma; (c) inversão de fila recorrente → confirma; (d) descartado (pronto pagamento legítimo / dezembro <40%);
(e) sem pagamentos → nao_avaliavel.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detector_x3.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS, ResultadoDetector
from compliance_agent.detectores.x3_execucao_financeira import X3ExecucaoFinanceira


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


# ═══════════════════════════════ (a) pagamento ANTES do atesto → forte ═══════════════════════════════
def test_x3_confirma_pagamento_antes_do_atesto():
    ctx = {
        "processo": "exec-1",
        "pagamentos": [
            {"data_empenho": "2024-03-01", "data_liquidacao": "2024-03-10", "data_pagamento": "2024-03-15",
             "data_atesto": "2024-03-20", "valor": 50000.0},  # pago ANTES do atesto
            {"data_pagamento": "2024-05-10", "data_atesto": "2024-05-01", "valor": 30000.0},  # ok
        ],
    }
    r = X3ExecucaoFinanceira().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["n_pagamentos_antes_do_atesto"] == 1
    assert r.evidencia


# ═══════════════════════════════ (b) ≥40% em dezembro + sem cronograma → forte ═══════════════════════════════
def test_x3_confirma_dezembro_sem_cronograma():
    ctx = {
        "processo": "exec-2",
        "tem_cronograma": False,
        "pagamentos": [
            {"data_pagamento": "2024-12-05", "valor": 60000.0},
            {"data_pagamento": "2024-12-20", "valor": 20000.0},
            {"data_pagamento": "2024-06-10", "valor": 20000.0},
        ],  # 80% do valor em dezembro
    }
    r = X3ExecucaoFinanceira().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["pct_dezembro"] >= 0.40


def test_x3_dezembro_com_cronograma_so_medio():
    """Dezembro ≥40% MAS COM cronograma → médio (não forte): a ausência de cronograma é o que agrava."""
    ctx = {
        "processo": "exec-2b",
        "tem_cronograma": True,
        "pagamentos": [
            {"data_pagamento": "2024-12-05", "valor": 60000.0},
            {"data_pagamento": "2024-06-10", "valor": 40000.0},
        ],
    }
    r = X3ExecucaoFinanceira().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert ANCORAS["medio"] <= r.score < ANCORAS["forte"]


# ═══════════════════════════════ (c) inversão de fila recorrente → confirma ═══════════════════════════════
def test_x3_confirma_inversao_fila():
    """Fila: contratos que chegaram antes pagos depois (furo de fila) recorrente → forte."""
    ctx = {
        "processo": "exec-3",
        "pagamentos": [{"data_pagamento": "2024-04-10", "valor": 10000.0}],
        "fila_orgao": [
            {"contrato": "A", "data_chegada": "2024-01-01", "data_pago": "2024-03-01"},
            {"contrato": "B", "data_chegada": "2024-01-02", "data_pago": "2024-01-10"},  # furou A
            {"contrato": "C", "data_chegada": "2024-01-03", "data_pago": "2024-01-12"},  # furou A
        ],
    }
    r = X3ExecucaoFinanceira().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["n_inversoes_fila"] >= 2


def test_x3_confirma_rubrica_quebra_inexistente():
    """Inversão de fila + rubrica injetada 'inexistente' (sem rede) → confirma forte, registra a quebra."""
    ctx = {
        "processo": "exec-3b",
        "pagamentos": [{"data_pagamento": "2024-04-10", "valor": 10000.0}],
        "fila_orgao": [
            {"contrato": "A", "data_chegada": "2024-01-01", "data_pago": "2024-03-01"},
            {"contrato": "B", "data_chegada": "2024-01-02", "data_pago": "2024-01-10"},
            {"contrato": "C", "data_chegada": "2024-01-03", "data_pago": "2024-01-12"},
        ],
        "_rubrica_quebra": {"nivel": "inexistente", "trecho": "sem ato de quebra publicado no DO"},
    }
    r = X3ExecucaoFinanceira().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["justificativa_quebra_ordem"] == "inexistente"


# ═══════════════════════════════ tríade comprimida ═══════════════════════════════
def test_x3_triade_comprimida_indicio_medio():
    """Ciclo empenho→pagamento < 3 dias (não pronto pagamento) → indício médio."""
    ctx = {
        "processo": "exec-4",
        "pagamentos": [
            {"data_empenho": "2024-07-01", "data_liquidacao": "2024-07-01", "data_pagamento": "2024-07-02",
             "valor": 25000.0},
        ],
    }
    r = X3ExecucaoFinanceira().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["medio"]
    assert r.valores["min_ciclo_empenho_pagamento_dias"] == 1


# ═══════════════════════════════ (d) descartados (exculpatórios) ═══════════════════════════════
def test_x3_descartado_pronto_pagamento_legitimo():
    """Tríade comprimida MAS objeto de PRONTO PAGAMENTO → compressão legítima → descartado."""
    ctx = {
        "processo": "exec-5",
        "tipo_objeto": "pronto_pagamento",
        "pagamentos": [
            {"data_empenho": "2024-07-01", "data_liquidacao": "2024-07-01", "data_pagamento": "2024-07-01",
             "valor": 5000.0},
        ],
    }
    r = X3ExecucaoFinanceira().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0
    assert r.valores["pronto_pagamento"] is True


def test_x3_descartado_dezembro_abaixo_do_limiar():
    """Dezembro <40% e nada mais anômalo → descartado."""
    ctx = {
        "processo": "exec-6",
        "tem_cronograma": False,
        "pagamentos": [
            {"data_pagamento": "2024-12-05", "valor": 20000.0},
            {"data_pagamento": "2024-06-10", "valor": 50000.0},
            {"data_pagamento": "2024-08-10", "valor": 50000.0},
        ],  # ~16% em dezembro
    }
    r = X3ExecucaoFinanceira().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0
    assert r.valores["pct_dezembro"] < 0.40


# ═══════════════════════════════ (e) sem pagamentos → nao_avaliavel ═══════════════════════════════
def test_x3_nao_avaliavel_sem_pagamentos():
    r = X3ExecucaoFinanceira().avaliar({"processo": "exec-7"})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.score == 0.0
    assert "tríade" in r.motivo_refutacao or "SIAFE" in r.motivo_refutacao


def test_x3_identidade_e_familia():
    det = X3ExecucaoFinanceira()
    assert det.id == "X3"
    assert det.familia == "execucao"
