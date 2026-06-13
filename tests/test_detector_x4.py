# -*- coding: utf-8 -*-
"""Teste TARGETED do detector da FASE DE EXECUÇÃO X4 (carona abusiva em ARP) — spec V2 do dono, §X4.

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO (dicts), LLM ausente OU rubrica pré-classificada
injetada (sem rede). Cobre: (a) adesão individual > 50% do registrado → viola §4º (crítico); (b) soma das adesões
> 2× o item → viola §5º (crítico); (c) rede coordenada via justificativas idênticas (similaridade ≥95%);
(d) rede coordenada via rubrica de concentração geográfica; (e) descartado (ata barata, adesões nos limites);
(f) sem ata → nao_avaliavel; (g) sem adesões → nao_avaliavel.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detector_x4.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS, ResultadoDetector
from compliance_agent.detectores.x4_carona_abusiva import X4CaronaAbusiva


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


# ═══════════════════════════ (a) adesão INDIVIDUAL > 50% → viola §4º (crítico) ═══════════════════════════
def test_x4_confirma_violacao_individual_50pct():
    ctx = {
        "processo": "x4-individual",
        "ata": {"orgao_gerenciador": "ORG-A", "itens": [{"item": "I1", "quantitativo_registrado": 1000}]},
        "adesoes": [
            {"aderente": "Pref X", "item": "I1", "quantidade": 600, "data": "2025-03-01"},  # 60% > 50%
        ],
    }
    r = X4CaronaAbusiva().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["critico"]
    assert r.valores["violacoes_individuais_50pct"]
    assert r.valores["violacoes_individuais_50pct"][0]["aderente"] == "Pref X"
    assert r.evidencia


# ═══════════════════════════ (b) SOMA das adesões > 2× → viola §5º (crítico) ═══════════════════════════
def test_x4_confirma_violacao_total_dobro():
    ctx = {
        "processo": "x4-total",
        "ata": {"itens": [{"item": "I1", "quantitativo_registrado": 100}]},
        "adesoes": [
            # cada aderente ≤50% (40 < 50), mas a SOMA (240) > 2× (200) → viola §5º, sem violar §4º
            {"aderente": "A", "item": "I1", "quantidade": 40},
            {"aderente": "B", "item": "I1", "quantidade": 40},
            {"aderente": "C", "item": "I1", "quantidade": 40},
            {"aderente": "D", "item": "I1", "quantidade": 40},
            {"aderente": "E", "item": "I1", "quantidade": 40},
            {"aderente": "F", "item": "I1", "quantidade": 40},
        ],
    }
    r = X4CaronaAbusiva().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["critico"]
    assert r.valores["violacoes_total_dobro"]
    assert not r.valores["violacoes_individuais_50pct"]  # nenhum estourou o §4º individual
    assert r.valores["violacoes_total_dobro"][0]["fracao"] > 2.0


# ═══════════════════════════ (c) rede coordenada via justificativas idênticas (≥95%) ═══════════════════════════
def test_x4_rede_coordenada_justificativas_identicas():
    just = ("Considerando a vantajosidade da adesão e a economicidade frente ao mercado, "
            "justifica-se a adesão a esta ata de registro de preços nos termos da lei.")
    ctx = {
        "processo": "x4-boilerplate",
        # adesões DENTRO dos limites (sem violação objetiva) — o sinal vem da rubrica de justificativa
        "ata": {"itens": [{"item": "I1", "quantitativo_registrado": 1000}]},
        "adesoes": [
            {"aderente": "Pref Y", "item": "I1", "quantidade": 100, "justificativa": just},
            {"aderente": "Pref Z", "item": "I1", "quantidade": 100, "justificativa": just},
        ],
    }
    r = X4CaronaAbusiva().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["rubrica_justificativa"] == "texto_padrao"
    assert r.valores["similaridade_justificativas"] >= 0.95


# ═══════════════════════════ (d) rede coordenada via rubrica de concentração geográfica ═══════════════════════════
def test_x4_rede_coordenada_concentracao_geografica():
    ctx = {
        "processo": "x4-geo",
        "ata": {"itens": [{"item": "I1", "quantitativo_registrado": 1000}]},
        "adesoes": [
            {"aderente": "Pref M", "item": "I1", "quantidade": 100, "municipio": "Vizinho 1"},
            {"aderente": "Pref N", "item": "I1", "quantidade": 100, "municipio": "Vizinho 2"},
        ],
        "_rubrica_rede": {"nivel": "concentracao_anomala",
                          "trecho": "aderentes concentrados em municípios vizinhos com vínculo ao fornecedor"},
    }
    r = X4CaronaAbusiva().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["rubrica_rede"] == "concentracao_anomala"


# ═══════════════════════════ (e) descartado: ata BARATA + adesões dentro dos limites ═══════════════════════════
def test_x4_descartado_ata_barata_dentro_dos_limites():
    ctx = {
        "processo": "x4-gestao",
        "ata": {"itens": [{"item": "I1", "quantitativo_registrado": 1000}]},
        "adesoes": [
            {"aderente": "A", "item": "I1", "quantidade": 100},  # 10% — bem abaixo de 50%
            {"aderente": "B", "item": "I1", "quantidade": 200},  # 20%
        ],
        "preco_ata_vs_mercado": 0.92,  # ata BARATA/justa → gestão, não esquema
    }
    r = X4CaronaAbusiva().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0
    assert not r.valores["violacoes_individuais_50pct"]
    assert not r.valores["violacoes_total_dobro"]


def test_x4_descartado_dentro_dos_limites_sem_rede():
    """Sem violação, sem preço informado, sem rede coordenada → descartado (sem indício)."""
    ctx = {
        "processo": "x4-limpo",
        "ata": {"itens": [{"item": "I1", "quantitativo_registrado": 1000}]},
        "adesoes": [
            {"aderente": "A", "item": "I1", "quantidade": 100},
        ],
    }
    r = X4CaronaAbusiva().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


# ═══════════════════════════ (f)/(g) honestidade: sem ata / sem adesões → nao_avaliavel ═══════════════════════════
def test_x4_sem_ata_nao_avaliavel():
    ctx = {
        "processo": "x4-sem-ata",
        "adesoes": [{"aderente": "A", "item": "I1", "quantidade": 600}],
    }
    r = X4CaronaAbusiva().avaliar(ctx)
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.score == 0.0


def test_x4_sem_adesoes_nao_avaliavel():
    ctx = {
        "processo": "x4-sem-adesoes",
        "ata": {"itens": [{"item": "I1", "quantitativo_registrado": 1000}]},
        "adesoes": [],
    }
    r = X4CaronaAbusiva().avaliar(ctx)
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.score == 0.0


def test_x4_ata_cara_com_violacao_agrava_narrativa():
    """Violação objetiva de limite + ata CARA: confirma crítico e registra o discriminador de preço."""
    ctx = {
        "processo": "x4-cara",
        "ata": {"itens": [{"item": "I1", "quantitativo_registrado": 100}]},
        "adesoes": [{"aderente": "A", "item": "I1", "quantidade": 70}],  # 70% > 50%
        "preco_ata_vs_mercado": 1.45,  # ata CARA → esquema
    }
    r = X4CaronaAbusiva().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["critico"]
    assert "cara" in r.motivo_refutacao.lower() or r.valores["preco_ata_vs_mercado"] == 1.45
