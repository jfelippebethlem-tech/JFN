# -*- coding: utf-8 -*-
"""Teste TARGETED do detector J7 (inabilitação seletiva / dois pesos) — spec V2 do dono, §J7.

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO (dicts), LLM ausente OU rubrica pré-classificada
injetada (sem rede). Cobre: (a) confirma com par crítico + equivalência injetada; (b) descartado quando a
rubrica diz 'falhas-distintas' (detector pareou errado); (c) descartado tratamento uniforme (art.64); (d)
sem decisões → nao_avaliavel; (e) classificação de classe por palavra-chave; (f) rubrica de fundamentação
contraditória eleva; (g) nao_avaliavel quando há par divergente mas equivalência não confirmada.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detector_j7.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS, ResultadoDetector
from compliance_agent.detectores.j7_inabilitacao_seletiva import (
    J7InabilitacaoSeletiva,
    classificar_classe_falha,
)


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


def _equiv(nivel: str) -> dict:
    return {"nivel": nivel, "trecho": "trechos das decisões lado a lado"}


# ═══════════════════════════════ (a) confirma — par crítico + equivalência ═══════════════════════════════
def test_j7_confirma_par_critico_certidao_vencida():
    """Mesma classe 'certidão vencida': perdedor INABILITADO × vencedor DILIGENCIADO, equivalência confirmada → forte/crítico."""
    ctx = {
        "processo": "j7-1",
        "comissao": "CPL-X",
        "decisoes": [
            {"cnpj": "11111111000100", "falha": "certidão vencida (regularidade fiscal)",
             "decisao": "inabilitado", "fundamento": "documento expirado, sem saneamento"},
            {"cnpj": "99999999000100", "falha": "certidão vencida (regularidade fiscal)",
             "decisao": "diligencia", "fundamento": "concedido prazo para sanar", "vencedor": True},
        ],
        "_rubrica_equivalencia": _equiv("falhas-equivalentes"),
    }
    r = J7InabilitacaoSeletiva().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.score == ANCORAS["critico"]  # tolerado é o vencedor → par crítico
    assert r.valores["n_pares_divergentes"] >= 1
    assert r.valores["equivalencia_falhas"] == "falhas-equivalentes"
    assert r.evidencia


def test_j7_confirma_par_nao_critico_sem_vencedor():
    """Par divergente mas o tolerado NÃO é o vencedor → forte (não crítico)."""
    ctx = {
        "processo": "j7-2",
        "decisoes": [
            {"cnpj": "1", "falha": "assinatura faltante na proposta", "decisao": "inabilitado"},
            {"cnpj": "2", "falha": "proposta sem assinatura do representante", "decisao": "saneamento"},
        ],
        "_rubrica_equivalencia": _equiv("falhas-equivalentes"),
    }
    r = J7InabilitacaoSeletiva().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["forte"]  # divergente equivalente, mas sem vencedor → não escala p/ crítico


def test_j7_fundamentacao_contraditoria_confirma():
    """Rubrica de fundamentação 'contraditória com decisão anterior da própria comissão' → forte."""
    ctx = {
        "processo": "j7-3",
        "decisoes": [
            {"cnpj": "1", "falha": "índice de liquidez abaixo do exigido", "decisao": "inabilitado"},
            {"cnpj": "2", "falha": "índice de endividamento fora do edital", "decisao": "diligencia", "vencedor": True},
        ],
        "_rubrica_equivalencia": _equiv("falhas-equivalentes"),
        "_rubrica_fundamentacao": {
            "nivel": "contraditoria-com-decisao-anterior-da-propria-comissao",
            "trecho": "em 2024 a mesma comissão inabilitou por índice idêntico"},
    }
    r = J7InabilitacaoSeletiva().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.valores["qualidade_fundamentacao"] == "contraditoria-com-decisao-anterior-da-propria-comissao"
    assert r.score >= ANCORAS["forte"]


# ═══════════════════════════════ (b) descartado — falhas-distintas (pareou errado) ═══════════════════════════════
def test_j7_descartado_falhas_distintas():
    """Rubrica equivalência 'falhas-distintas': o detector pareou errado → descartado (protege falso positivo)."""
    ctx = {
        "processo": "j7-4",
        "decisoes": [
            {"cnpj": "1", "falha": "atestado de capacidade técnica insuficiente", "decisao": "inabilitado"},
            {"cnpj": "2", "falha": "atestado com erro de digitação no número", "decisao": "diligencia", "vencedor": True},
        ],
        "_rubrica_equivalencia": _equiv("falhas-distintas"),
    }
    r = J7InabilitacaoSeletiva().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0
    assert r.valores["equivalencia_falhas"] == "falhas-distintas"


# ═══════════════════════════════ (c) descartado — tratamento uniforme (art.64) ═══════════════════════════════
def test_j7_descartado_saneamento_uniforme():
    """Todos com mesma classe de falha receberam saneamento (mesma régua) → art.64 legítimo → descartado."""
    ctx = {
        "processo": "j7-5",
        "decisoes": [
            {"cnpj": "1", "falha": "certidão vencida", "decisao": "saneamento"},
            {"cnpj": "2", "falha": "certidão vencida", "decisao": "diligencia"},
            {"cnpj": "3", "falha": "certidão vencida", "decisao": "saneamento"},
        ],
        "_rubrica_equivalencia": _equiv("falhas-equivalentes"),
    }
    r = J7InabilitacaoSeletiva().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0
    assert r.valores["n_pares_divergentes"] == 0


def test_j7_descartado_inabilitacao_uniforme():
    """Todos da mesma classe inabilitados (mesma régua) → sem divergência → descartado."""
    ctx = {
        "processo": "j7-5b",
        "decisoes": [
            {"cnpj": "1", "falha": "assinatura faltante", "decisao": "inabilitado"},
            {"cnpj": "2", "falha": "assinatura faltante", "decisao": "inabilitado"},
        ],
    }
    r = J7InabilitacaoSeletiva().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"


# ═══════════════════════════════ (d) sem decisões → nao_avaliavel ═══════════════════════════════
def test_j7_nao_avaliavel_sem_decisoes():
    r = J7InabilitacaoSeletiva().avaliar({"processo": "j7-6"})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.score == 0.0
    assert r.valores["tem_pares"] is False


def test_j7_nao_avaliavel_uma_so_decisao():
    """1 decisão isolada não forma par (a unidade de análise é o PAR) → nao_avaliavel."""
    ctx = {"processo": "j7-7",
           "decisoes": [{"cnpj": "1", "falha": "certidão vencida", "decisao": "inabilitado"}]}
    r = J7InabilitacaoSeletiva().avaliar(ctx)
    _valido(r)
    assert r.status == "nao_avaliavel"


# ═══════════════════════════════ (e) classificação de classe por palavra-chave ═══════════════════════════════
def test_j7_classificacao_classe_por_palavra_chave():
    assert classificar_classe_falha("Certidão Vencida de regularidade fiscal") == "certidao_vencida"
    assert classificar_classe_falha("proposta sem assinatura") == "assinatura"
    assert classificar_classe_falha("índice de liquidez insuficiente") == "indice_contabil"
    assert classificar_classe_falha("atestado de capacidade técnica") == "atestado"
    assert classificar_classe_falha("documentação incompleta") == "documentacao"
    assert classificar_classe_falha("motivo totalmente atípico xyz") == "outra"
    assert classificar_classe_falha("") == "outra"


def test_j7_serie_comissao_pareia_entre_sessoes():
    """Decisão atual + decisão histórica da MESMA comissão (serie_comissao) pareiam entre sessões."""
    ctx = {
        "processo": "j7-8",
        "decisoes": [
            {"cnpj": "1", "falha": "certidão vencida", "decisao": "inabilitado"},
        ],
        "serie_comissao": [
            {"cnpj": "2", "falha": "certidão vencida", "decisao": "diligencia", "vencedor": True},
        ],
        "_rubrica_equivalencia": _equiv("falhas-equivalentes"),
    }
    r = J7InabilitacaoSeletiva().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.valores["n_decisoes_validas"] == 2


# ═══════════════════════════════ (g) par divergente mas equivalência não confirmada ═══════════════════════════════
def test_j7_nao_avaliavel_sem_confirmacao_equivalencia():
    """Pareamento objetivo achou divergência, MAS sem LLM/rubrica a equivalência não é confirmada → nao_avaliavel."""
    ctx = {
        "processo": "j7-9",
        "decisoes": [
            {"cnpj": "1", "falha": "certidão vencida", "decisao": "inabilitado"},
            {"cnpj": "2", "falha": "certidão vencida", "decisao": "diligencia", "vencedor": True},
        ],
        # sem _rubrica_equivalencia e sem gerar → equivalência fica nao_avaliavel
    }
    r = J7InabilitacaoSeletiva().avaliar(ctx)
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.valores["n_pares_divergentes"] >= 1
    assert r.evidencia  # ainda registra os pares achados (transparência)
