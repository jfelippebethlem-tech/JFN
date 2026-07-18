# -*- coding: utf-8 -*-
"""Teste TARGETED do detector E5 — EDITAL ITERADO (republicações dirigidas), spec V2 §3/E5.

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO DE EDITAL (dicts), LLM ausente OU rubricas
pré-classificadas injetadas (`_rubricas_alteracoes`, sem rede). Cobre: confirma (republicações + rubrica
restritiva que casa com o vencedor), descartado (origem TCE/erro material; ampliação de competição), sem versões
suficientes → nao_avaliavel, impugnação → exclusão do impugnante. Partes OBJETIVAS determinísticas (limiar no
código). Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detector_e5.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS, ResultadoDetector
from compliance_agent.detectores.e5_edital_iterado import E5EditalIterado


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


def _versoes(n: int) -> list[dict]:
    return [{"versao": i + 1, "data": f"2024-0{i + 1}-01"} for i in range(n)]


# ═══════════════════════════════ (a) CONFIRMA ═══════════════════════════════
def test_e5_confirma_rubrica_restritiva_casa_com_vencedor():
    """Várias retificações 'de ofício' + rubrica 'restringe_ou_beneficia_perfil_especifico' que CASA com a
    característica do vencedor final → forte."""
    ctx = {
        "processo": "ed5-1",
        "versoes": _versoes(4),
        "retificacoes": [
            {"secao": "habilitacao", "antes": "qualquer", "depois": "certificacao iso 9001",
             "origem": "oficio"},
            {"secao": "atestado", "antes": "1 atestado", "depois": "3 atestados regionais", "origem": "oficio"},
        ],
        "vencedor": {"cnpj": "12.345.678/0001-90", "caracteristicas": ["iso 9001", "sede regional"]},
        "_rubricas_alteracoes": [
            {"nivel": "restringe_ou_beneficia_perfil_especifico",
             "trecho": "certificacao iso 9001", "perfil_beneficiado": "empresa com iso 9001"},
            {"nivel": "neutra", "trecho": "ajuste de redacao"},
        ],
    }
    r = E5EditalIterado().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["confirma_perfil_vencedor"] is True or \
        "restringe_ou_beneficia_perfil_especifico" in r.valores["beneficiario_alteracoes"]
    assert r.evidencia


def test_e5_confirma_volume_republicacoes_objetivo():
    """Volume alto de republicações (>=4) é flag OBJETIVO mesmo sem rubrica (componente subjetivo nao_avaliavel)."""
    ctx = {"processo": "ed5-2", "versoes": _versoes(5)}  # 4 republicações
    r = E5EditalIterado().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["n_republicacoes"] == 4


def test_e5_confirma_ciclo_termina_em_dispensa():
    """Ciclo deserto/fracassado recorrente que termina em DISPENSA → forte (motivação fabricada)."""
    ctx = {
        "processo": "ed5-3",
        "versoes": [
            {"versao": 1, "resultado": "deserto"},
            {"versao": 2, "resultado": "fracassado"},
            {"versao": 3, "resultado": "deserto"},
        ],
        "resultado_final": "dispensa",
    }
    r = E5EditalIterado().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["n_rodadas_fracassadas"] >= 1
    assert r.valores["resultado_final"] == "dispensa"


# ═══════════════════════════════ (d) IMPUGNAÇÃO → EXCLUSÃO ═══════════════════════════════
def test_e5_confirma_impugnacao_exclui_impugnante():
    """Impugnação de um licitante seguida de mudança que o EXCLUI → forte."""
    ctx = {
        "processo": "ed5-4",
        "versoes": _versoes(2),
        "impugnacoes": [
            {"licitante": "Alfa Ltda", "pedido": "relaxar atestado",
             "atendida": False, "mudanca_exclui_impugnante": True},
        ],
    }
    r = E5EditalIterado().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["impugnacao_exclui_impugnante"] is True
    assert r.evidencia


# ═══════════════════════════════ (b) DESCARTADO (exculpatório) ═══════════════════════════════
def test_e5_descartado_origem_tce_legitima():
    """Todas as retificações por DETERMINAÇÃO do TCE → republicação legítima, descartado."""
    ctx = {
        "processo": "ed5-5",
        "versoes": _versoes(4),
        "retificacoes": [
            {"secao": "habilitacao", "antes": "a", "depois": "b", "origem": "tce"},
            {"secao": "objeto", "antes": "c", "depois": "d", "origem": "tce"},
            {"secao": "anexo", "antes": "e", "depois": "f", "origem": "erro_material"},
        ],
    }
    r = E5EditalIterado().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0
    assert r.valores["n_retificacoes_legitimas"] == 3
    assert r.valores["n_retificacoes_relevantes"] == 0


def test_e5_descartado_erro_material():
    """Retificação isolada por erro material (sem volume nem outros indícios) → descartado."""
    ctx = {
        "processo": "ed5-6",
        "versoes": _versoes(2),
        "retificacoes": [{"secao": "edital", "antes": "data errada", "depois": "data correta",
                          "origem": "erro_material"}],
    }
    r = E5EditalIterado().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_e5_descartado_amplia_competicao_pos_impugnacao():
    """Retificações 'de ofício' mas rubrica diz que AMPLIAM competição (relaxam exigências) → comportamento
    correto, zera o detector."""
    ctx = {
        "processo": "ed5-7",
        "versoes": _versoes(3),
        "retificacoes": [
            {"secao": "habilitacao", "antes": "3 atestados", "depois": "1 atestado", "origem": "oficio"},
            {"secao": "capital", "antes": "10%", "depois": "5%", "origem": "oficio"},
        ],
        "impugnacoes": [{"licitante": "Beta", "pedido": "relaxar", "atendida": True,
                         "mudanca_exclui_impugnante": False}],
        "_rubricas_alteracoes": [
            {"nivel": "amplia_competicao", "trecho": "reduz para 1 atestado"},
            {"nivel": "amplia_competicao", "trecho": "reduz capital para 5%"},
        ],
    }
    r = E5EditalIterado().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0
    assert r.valores["impugnacoes_que_ampliam"] >= 1


# ═══════════════════════════════ (c) NAO_AVALIAVEL ═══════════════════════════════
def test_e5_nao_avaliavel_sem_versoes():
    r = E5EditalIterado().avaliar({"processo": "ed5-8"})
    _valido(r)
    assert r.status == "nao_avaliavel"


def test_e5_nao_avaliavel_uma_versao_sem_retificacao():
    """Uma única versão e nenhuma retificação → não há iteração para avaliar (campo ausente ≠ 0)."""
    ctx = {"processo": "ed5-9", "versoes": _versoes(1)}
    r = E5EditalIterado().avaliar(ctx)
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.valores["n_versoes"] == 1


# ═══════════════════════════════ honestidade do componente subjetivo ═══════════════════════════════
def test_e5_subjetivo_nao_avaliavel_sem_llm():
    """Poucas republicações (2) e retificação relevante SEM LLM/rubrica → subjetivo nao_avaliavel, e como não
    há flag objetivo (volume<3, sem ciclo/impugnação) → descartado honesto (não inventa juízo)."""
    ctx = {
        "processo": "ed5-10",
        "versoes": _versoes(2),
        "retificacoes": [{"secao": "x", "antes": "a", "depois": "b", "origem": "oficio"}],
    }
    r = E5EditalIterado().avaliar(ctx)
    _valido(r)
    assert "nao_avaliavel" in r.valores["beneficiario_alteracoes"]
    assert r.status == "descartado"


def test_e5_esclarecimentos_nao_contam_no_volume():
    """Esclarecimentos triviais entram no diff mas NÃO no contador de volume: 4 esclarecimentos + 2 versões
    não viram '4 republicações' (era falso positivo de iteração dirigida)."""
    ctx = {
        "processo": "ed5-12",
        "versoes": _versoes(2),
        "retificacoes": [
            {"secao": f"duvida-{i}", "antes": "?", "depois": "resposta", "origem": "oficio",
             "tipo": "esclarecimento"}
            for i in range(4)
        ],
    }
    r = E5EditalIterado().avaliar(ctx)
    _valido(r)
    assert r.valores["n_republicacoes"] == 1        # só a republicação por versão conta
    assert r.valores["n_retificacoes_no_volume"] == 0
    assert r.status == "descartado"


def test_e5_retificacao_com_reabertura_conta_no_volume():
    """Retificação que materializou republicação (nova versão publicada / reabertura de prazo) conta."""
    ctx = {
        "processo": "ed5-13",
        "versoes": _versoes(2),
        "retificacoes": [
            {"secao": "hab", "antes": "a", "depois": "b", "origem": "oficio", "nova_versao": True},
            {"secao": "obj", "antes": "c", "depois": "d", "origem": "oficio", "reabriu_prazo": True},
            {"secao": "anexo", "antes": "e", "depois": "f", "origem": "oficio", "nova_versao": True},
        ],
    }
    r = E5EditalIterado().avaliar(ctx)
    _valido(r)
    assert r.valores["n_retificacoes_no_volume"] == 3
    assert r.valores["n_republicacoes"] == 3
    assert r.status == "confirmado"


def test_e5_caracteristica_curta_ou_parcial_nao_casa_vencedor():
    """Guarda anti-FP do casamento com o vencedor: característica curta ('me', 'rj') ou casamento sem
    fronteira de palavra ('regional' em 'regionalizada') não confirmam o perfil."""
    ctx = {
        "processo": "ed5-14",
        "versoes": _versoes(5),   # volume objetivo sustenta o confirmado
        "retificacoes": [{"secao": "hab", "antes": "a", "depois": "b", "origem": "oficio"}],
        "vencedor": {"cnpj": "00.000.000/0001-00", "caracteristicas": ["me", "rj", "regional"]},
        "_rubricas_alteracoes": [
            {"nivel": "restringe_ou_beneficia_perfil_especifico",
             "trecho": "exige atestado emitido por empresa regionalizada", "perfil_beneficiado": "certame"},
        ],
    }
    r = E5EditalIterado().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"                     # volume >=4 sustenta
    assert r.valores["confirma_perfil_vencedor"] is False


def test_e5_restritiva_sem_caracteristica_vencedor_nao_confirma_perfil():
    """Rubrica restritiva mas SEM características do vencedor → não há casamento confirmado; o volume objetivo
    (>=4 republicações) ainda confirma, mas confirma_perfil_vencedor permanece False (honesto)."""
    ctx = {
        "processo": "ed5-11",
        "versoes": _versoes(5),
        "retificacoes": [{"secao": "hab", "antes": "a", "depois": "b", "origem": "oficio"}],
        "vencedor": {"cnpj": "00.000.000/0001-00"},  # sem caracteristicas
        "_rubricas_alteracoes": [
            {"nivel": "restringe_ou_beneficia_perfil_especifico", "trecho": "exige X", "perfil_beneficiado": "Y"},
        ],
    }
    r = E5EditalIterado().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"  # volume >=4 sustenta
    assert r.valores["confirma_perfil_vencedor"] is False
