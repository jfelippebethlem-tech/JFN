# -*- coding: utf-8 -*-
"""Teste TARGETED do detector E6 (pontuação técnica dirigida) — fase de EDITAL, spec V2.

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO DE EDITAL (dicts), LLM ausente OU rubrica
pré-classificada injetada (sem rede). As partes OBJETIVAS são determinísticas (% subjetivo + simulação de troca
de vencedor, limiar no código). Cobre: (a) confirma por ≥40% subjetivo + simulação muda vencedor; (b) confirma
FORTE por subjetivo + ata sem fundamentação (rubrica); (c) descartado (serviço intelectual legítimo + objetivo);
(d) sem matriz → nao_avaliavel. Rodar só este arquivo:
    .venv/bin/python -m pytest tests/test_detector_e6.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS, ResultadoDetector
from compliance_agent.detectores.e6_pontuacao_dirigida import E6PontuacaoDirigida


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


# ───────────────────────── fixtures ─────────────────────────
def _matriz_dirigida():
    """Matriz com 50% dos pontos em subjetivo_puro (campo direto, sem LLM)."""
    return [
        {"criterio": "atestado de capacidade", "pontos": 30, "subjetividade": "objetivo_verificavel"},
        {"criterio": "titulação da equipe", "pontos": 20, "subjetividade": "semiobjetivo"},
        {"criterio": "qualidade da metodologia", "pontos": 50, "subjetividade": "subjetivo_puro"},
    ]


def _propostas_vencedor_dirigido():
    """A vence por causa do critério subjetivo; sem ele, B vence."""
    return [
        {"cnpj": "A", "notas": {"atestado de capacidade": 20, "titulação da equipe": 10, "qualidade da metodologia": 50}},
        {"cnpj": "B", "notas": {"atestado de capacidade": 30, "titulação da equipe": 20, "qualidade da metodologia": 10}},
    ]


# ═══════════════════════════════ (a) confirma — subjetivo + simulação ═══════════════════════════════
def test_e6_confirma_subjetivo_e_simulacao_muda_vencedor():
    """≥40% pontos subjetivo_puro (campo direto) + simulação zerando-o muda o vencedor → forte."""
    ctx = {
        "processo": "tp-1",
        "matriz_pontuacao": _matriz_dirigida(),
        "propostas_tecnicas": _propostas_vencedor_dirigido(),
        "vencedor_cnpj": "A",
    }
    r = E6PontuacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["pct_subjetivo"] == 0.5
    assert r.valores["simulacao"]["vencedor_muda"] is True
    assert r.valores["simulacao"]["vencedor_sem"] == "B"
    assert r.evidencia


def test_e6_confirma_apenas_percentual_subjetivo_medio():
    """≥40% subjetivo sem simulação (sem propostas) → médio (matriz frouxa, candidato)."""
    ctx = {"processo": "tp-2", "matriz_pontuacao": _matriz_dirigida()}
    r = E6PontuacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["medio"]
    assert r.valores["simulacao"]["vencedor_muda"] is False


def test_e6_confirma_experiencia_proprio_orgao_agrava():
    """Critério que exige experiência com o PRÓPRIO órgão → barreira a entrantes (médio mesmo sem subjetivo alto)."""
    ctx = {
        "processo": "tp-3",
        "matriz_pontuacao": [
            {"criterio": "atestado geral", "pontos": 70, "subjetividade": "objetivo_verificavel"},
            {"criterio": "experiência prévia com o órgão", "pontos": 30,
             "subjetividade": "objetivo_verificavel", "exige_experiencia_proprio_orgao": True},
        ],
    }
    r = E6PontuacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["medio"]
    assert "experiência prévia com o órgão" in r.valores["criterios_proprio_orgao"]


# ═══════════════════════════════ (b) confirma FORTE — ata sem fundamentação ═══════════════════════════════
def test_e6_confirma_forte_ata_sem_fundamentacao():
    """Subjetivo-puro + rubrica de consistência 'notas_sem_fundamentacao' (injetada) → forte (arbítrio)."""
    ctx = {
        "processo": "tp-4",
        "matriz_pontuacao": _matriz_dirigida(),
        "atas": "Atribuída nota máxima ao proponente A. Demais propostas pontuadas a critério da comissão.",
        "_rubrica_consistencia": {"nivel": "notas_sem_fundamentacao",
                                  "trecho": "pontuadas a critério da comissão"},
    }
    r = E6PontuacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["consistencia_notas"] == "notas_sem_fundamentacao"
    # evidência deve conter o trecho da ata
    assert any("comissão" in e["trecho"] for e in r.evidencia)


def test_e6_rubrica_objetividade_via_llm_injetada():
    """Sem campo `subjetividade`: a rubrica de objetividade por critério (injetada) classifica subjetivo_puro."""
    ctx = {
        "processo": "tp-5",
        "matriz_pontuacao": [
            {"criterio": "atestado", "pontos": 40},
            {"criterio": "metodologia", "pontos": 60},
        ],
        "_rubricas_objetividade": [
            {"nivel": "objetivo_verificavel", "trecho": "atestado de capacidade técnica"},
            {"nivel": "subjetivo_puro", "trecho": "qualidade e adequação da metodologia"},
        ],
    }
    r = E6PontuacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.valores["pct_subjetivo"] == 0.6
    assert "metodologia" in r.valores["criterios_subjetivos"]


# ═══════════════════════════════ (c) descartado — serviço intelectual legítimo ═══════════════════════════════
def test_e6_descartado_servico_intelectual_objetivo():
    """Serviço intelectual (peso técnico alto legítimo) + critérios OBJETIVOS → descartado (exculpatória do spec)."""
    ctx = {
        "processo": "tp-6",
        "servico_intelectual": True,
        "matriz_pontuacao": [
            {"criterio": "atestados de projetos similares", "pontos": 60, "subjetividade": "objetivo_verificavel"},
            {"criterio": "titulação acadêmica da equipe", "pontos": 40, "subjetividade": "semiobjetivo"},
        ],
    }
    r = E6PontuacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0
    assert r.valores["servico_intelectual"] is True


def test_e6_servico_intelectual_nao_salva_matriz_subjetiva():
    """Serviço intelectual NÃO neutraliza subjetividade decisiva: subjetivo-puro + simulação decisiva → confirma."""
    ctx = {
        "processo": "tp-7",
        "servico_intelectual": True,
        "matriz_pontuacao": _matriz_dirigida(),
        "propostas_tecnicas": _propostas_vencedor_dirigido(),
        "vencedor_cnpj": "A",
    }
    r = E6PontuacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]


def test_e6_descartado_matriz_objetiva():
    """Matriz predominantemente objetiva (<40% subjetivo), sem próprio-órgão, sem troca → descartado."""
    ctx = {
        "processo": "tp-8",
        "matriz_pontuacao": [
            {"criterio": "atestado", "pontos": 80, "subjetividade": "objetivo_verificavel"},
            {"criterio": "prazo proposto", "pontos": 20, "subjetividade": "semiobjetivo"},
        ],
    }
    r = E6PontuacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


# ═══════════════════════════════ (d) nao_avaliavel — honestidade ═══════════════════════════════
def test_e6_nao_avaliavel_sem_matriz():
    r = E6PontuacaoDirigida().avaliar({"processo": "tp-9"})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert "matriz" in r.motivo_refutacao


def test_e6_nao_avaliavel_matriz_sem_pontos():
    """Matriz existe mas critérios sem pontos → não dá p/ medir % → nao_avaliavel honesto."""
    ctx = {"processo": "tp-10", "matriz_pontuacao": [
        {"criterio": "x", "subjetividade": "subjetivo_puro"},
        {"criterio": "y", "subjetividade": "objetivo_verificavel"},
    ]}
    r = E6PontuacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.status == "nao_avaliavel"


def test_e6_simulacao_sem_propostas_nao_quebra():
    """Sem propostas a simulação não roda (vencedor_muda=False) e não quebra; % subjetivo ainda confirma médio."""
    ctx = {"processo": "tp-11", "matriz_pontuacao": _matriz_dirigida()}
    r = E6PontuacaoDirigida().avaliar(ctx)
    _valido(r)
    assert r.valores["simulacao"]["vencedor_muda"] is False
    assert r.status == "confirmado"
