# -*- coding: utf-8 -*-
"""Teste TARGETED do detector E4 · VISITA TÉCNICA COMO FILTRO (spec V2 do dono, §3/E4).

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO DE EDITAL (dicts), LLM ausente OU rubrica de
necessidade pré-classificada injetada (sem rede). Partes OBJETIVAS são determinísticas (limiar no código:
obrigatoriedade sem alternativa, agendamento/janela, taxa de evasão, evadidos recorrentes). Casos:
(a) confirma por objeto padronizado (rubrica 'dispensavel'); (b) confirma por evasão alta; (c) descartado
(alternativa de declaração / objeto de engenharia peculiar via rubrica 'indispensavel'); (d) sem cláusula →
nao_avaliavel.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detector_e4.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS, ResultadoDetector
from compliance_agent.detectores.e4_visita_tecnica import E4VisitaTecnica


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


# ═══════════════════════════════ (a) confirma — objeto padronizado, rubrica 'dispensavel' ═══════════════════════════════
def test_e4_confirma_obrigatoria_objeto_padronizado_dispensavel():
    """Visita obrigatória sem alternativa + rubrica de necessidade 'dispensavel' (objeto padronizado) → forte."""
    ctx = {
        "processo": "visita-1",
        "visita": {"obrigatoria": True, "alternativa_declaracao": False},
        "objeto": "aquisição de material de escritório padronizado",
        "_rubrica_necessidade": {"nivel": "dispensavel", "trecho": "material de escritório padronizado"},
    }
    r = E4VisitaTecnica().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["necessidade"] == "dispensavel"
    assert r.evidencia


def test_e4_obrigatoria_sem_rubrica_so_medio():
    """Visita obrigatória sem alternativa, sem rubrica/LLM → 'medio' (candidato), necessidade nao_avaliavel."""
    ctx = {
        "processo": "visita-1b",
        "visita": {"obrigatoria": True, "alternativa_declaracao": False},
    }
    r = E4VisitaTecnica().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["medio"]
    assert r.valores["necessidade"] == "nao_avaliavel"


def test_e4_agendamento_controlado_agrava_para_forte():
    """Obrigatória + agendamento controlado / janela estreita → agrava de medio para forte."""
    ctx = {
        "processo": "visita-1c",
        "visita": {"obrigatoria": True, "alternativa_declaracao": False,
                   "agendamento_controlado": True, "janela_dias": 1},
    }
    r = E4VisitaTecnica().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["janela_estreita"] is True


# ═══════════════════════════════ (b) confirma por EVASÃO alta ═══════════════════════════════
def test_e4_confirma_evasao_alta():
    """Muitos visitantes, poucos viraram licitante → taxa de evasão alta → forte."""
    ctx = {
        "processo": "visita-2",
        "visita": {"obrigatoria": True, "alternativa_declaracao": False},
        "visitantes": ["11111111000111", "22222222000122", "33333333000133", "44444444000144"],
        "licitantes": ["11111111000111"],   # 3 de 4 evadiram = 75%
    }
    r = E4VisitaTecnica().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["taxa_evasao"] == 0.75
    assert r.valores["n_evadidos"] == 3


def test_e4_evasao_amostra_pequena_rebaixa_a_fraco():
    """Evasão de 50% mas com só 2 visitantes (n<4) → amostra pequena não sustenta 'forte'; fica no 'medio'
    da obrigatoriedade (a evasão entra rebaixada a fraco, com ressalva na razão)."""
    ctx = {
        "processo": "visita-2c",
        "visita": {"obrigatoria": True, "alternativa_declaracao": False},
        "visitantes": ["11111111000111", "22222222000122"],
        "licitantes": ["11111111000111"],   # 1 de 2 evadiu = 50%, n=2
    }
    r = E4VisitaTecnica().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score < ANCORAS["forte"]
    assert "amostra pequena" in r.motivo_refutacao


def test_e4_evadidos_recorrentes_correlacao_j1_j4():
    """Evadidos que também 'desistem' em outros certames (J1/J4) → agrava para forte e vira evidência."""
    ctx = {
        "processo": "visita-2b",
        "visita": {"obrigatoria": True, "alternativa_declaracao": False},
        "visitantes": ["11111111000111", "22222222000122"],
        "licitantes": ["11111111000111"],          # 22... evadiu
        "evadidos_em_outros_certames": ["22222222000122"],
    }
    r = E4VisitaTecnica().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert "22222222000122" in r.valores["evadidos_recorrentes"]


# ═══════════════════════════════ (c) descartado / exculpatório ═══════════════════════════════
def test_e4_descartado_alternativa_declaracao():
    """Visita com alternativa de declaração de conhecimento do local → descartado (jurisprudência atendida)."""
    ctx = {
        "processo": "visita-3",
        "visita": {"obrigatoria": True, "alternativa_declaracao": True},
    }
    r = E4VisitaTecnica().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_e4_exculpatorio_engenharia_peculiar_indispensavel():
    """Objeto de engenharia em local peculiar, rubrica 'indispensavel' → exculpatória, score ≤ fraco."""
    ctx = {
        "processo": "visita-3b",
        "visita": {"obrigatoria": True, "alternativa_declaracao": False},
        "objeto": "reforma de obra em encosta com fundação em terreno específico",
        "_rubrica_necessidade": {"nivel": "indispensavel", "trecho": "fundação em terreno específico"},
    }
    r = E4VisitaTecnica().avaliar(ctx)
    _valido(r)
    assert r.score <= ANCORAS["fraco"]
    assert r.valores["necessidade"] == "indispensavel"


def test_e4_facultativa_descartada():
    """Visita NÃO obrigatória, sem evasão → descartado."""
    ctx = {
        "processo": "visita-3c",
        "visita": {"obrigatoria": False, "alternativa_declaracao": False},
    }
    r = E4VisitaTecnica().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


# ═══════════════════════════════ (d) sem cláusula → nao_avaliavel ═══════════════════════════════
def test_e4_nao_avaliavel_sem_clausula_visita():
    """Sem cláusula de visita no contexto → nao_avaliavel (campo ausente ≠ 0)."""
    r = E4VisitaTecnica().avaliar({"processo": "visita-4"})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.valores["tem_clausula_visita"] is False


def test_e4_nao_avaliavel_visita_nao_dict():
    """visita presente mas tipo inválido (não-dict) → nao_avaliavel honesto."""
    r = E4VisitaTecnica().avaliar({"processo": "visita-4b", "visita": "obrigatória"})
    _valido(r)
    assert r.status == "nao_avaliavel"
