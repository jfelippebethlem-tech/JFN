# -*- coding: utf-8 -*-
"""Teste TARGETED do detector J5 (digitais compartilhadas: metadados, redação e origem) — spec V2 do dono.

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO (dicts), LLM ausente OU rubrica pré-classificada
injetada (sem rede). Cobre: (a) confirma (Author não-genérico compartilhado / mesmo contador CRC / mesmo IP);
(b) descartado (só Producer genérico 'Microsoft Word' compartilhado → não pontua); (c) sem propostas/metadados →
nao_avaliavel; (d) rubrica de erros idênticos injetada → eleva.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detector_j5.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS, ResultadoDetector
from compliance_agent.detectores.j5_digitais_compartilhadas import J5DigitaisCompartilhadas


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


# ═══════════════════════════════ (a) CONFIRMA ═══════════════════════════════
def test_j5_confirma_author_nao_generico_compartilhado():
    """Mesmo Author não-genérico entre 2 licitantes distintos → forte."""
    ctx = {
        "processo": "j5-1",
        "propostas": [
            {"licitante_cnpj": "11111111000100",
             "metadados": {"author": "Joao Escritorio Contabil ME", "producer": "Microsoft Word"}},
            {"licitante_cnpj": "22222222000100",
             "metadados": {"author": "Joao Escritorio Contabil ME", "producer": "Microsoft Word"}},
        ],
    }
    r = J5DigitaisCompartilhadas().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.evidencia
    assert r.valores["coincidencias"]["metadado"]


def test_j5_confirma_mesmo_contador_crc():
    """Mesmo contador (CRC) entre licitantes distintos → forte."""
    ctx = {
        "processo": "j5-2",
        "propostas": [
            {"licitante_cnpj": "11111111000100", "contatos": {"contador_crc": "CRC-RJ-123456"}},
            {"licitante_cnpj": "22222222000100", "contatos": {"contador_crc": "CRC-RJ-123456"}},
        ],
    }
    r = J5DigitaisCompartilhadas().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["coincidencias"]["contato"]


def test_j5_mesmo_ip_envio_eleva_para_critico():
    """Mesmo IP de envio entre licitantes distintos → crítico."""
    ctx = {
        "processo": "j5-3",
        "propostas": [
            {"licitante_cnpj": "11111111000100", "ip_envio": "200.10.20.30"},
            {"licitante_cnpj": "22222222000100", "ip_envio": "200.10.20.30"},
        ],
    }
    r = J5DigitaisCompartilhadas().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["critico"]
    assert r.valores["coincidencias"]["ip_envio"]


# ═══════════════════════════════ (b) DESCARTADO ═══════════════════════════════
def test_j5_descartado_so_producer_generico():
    """Só Producer genérico 'Microsoft Word' compartilhado → não pontua → descartado."""
    ctx = {
        "processo": "j5-4",
        "propostas": [
            {"licitante_cnpj": "11111111000100",
             "metadados": {"producer": "Microsoft Word", "author": "Empresa Alfa Ltda"}},
            {"licitante_cnpj": "22222222000100",
             "metadados": {"producer": "Microsoft Word", "author": "Empresa Beta Ltda"}},
        ],
    }
    r = J5DigitaisCompartilhadas().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_j5_descartado_author_generico_compartilhado():
    """Author genérico ('Windows User') idêntico → não pontua (universal) → descartado."""
    ctx = {
        "processo": "j5-4b",
        "propostas": [
            {"licitante_cnpj": "11111111000100", "metadados": {"author": "Windows User"}},
            {"licitante_cnpj": "22222222000100", "metadados": {"author": "Windows User"}},
        ],
    }
    r = J5DigitaisCompartilhadas().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


# ═══════════════════════════════ (c) NAO_AVALIAVEL ═══════════════════════════════
def test_j5_nao_avaliavel_sem_propostas():
    """Sem propostas → nao_avaliavel (campo essencial ausente ≠ 0)."""
    r = J5DigitaisCompartilhadas().avaliar({"processo": "j5-5"})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.score == 0.0


def test_j5_nao_avaliavel_uma_so_proposta_com_metadados():
    """Só 1 proposta com metadados (gap PNCP: só o vencedor) → nao_avaliavel."""
    ctx = {
        "processo": "j5-6",
        "propostas": [
            {"licitante_cnpj": "11111111000100", "metadados": {"author": "Joao ME"}},
            {"licitante_cnpj": "22222222000100"},  # sem metadados/contatos/origem
        ],
    }
    r = J5DigitaisCompartilhadas().avaliar(ctx)
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.valores["n_uteis"] == 1


# ═══════════════════════════════ (d) RUBRICA ═══════════════════════════════
def test_j5_rubrica_erros_identicos_eleva():
    """Rubrica injetada 'erros_identicos_improvaveis' (sem rede) → eleva para forte mesmo sem metadado coincidente."""
    ctx = {
        "processo": "j5-7",
        "propostas": [
            {"licitante_cnpj": "11111111000100", "metadados": {"author": "Alfa Ltda"}},
            {"licitante_cnpj": "22222222000100", "metadados": {"author": "Beta Ltda"}},
        ],
        "_rubrica_erros": {"nivel": "erros_identicos_improvaveis",
                           "trecho": "ambas: 'fornecimeto de equipamentos hosìpitalares' (mesmo erro raro)"},
    }
    r = J5DigitaisCompartilhadas().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["erros_textuais"] == "erros_identicos_improvaveis"


def test_j5_rubrica_sem_trecho_descartada_honesto():
    """Rubrica de erros sem citação literal (trecho) → descartada (regra de ouro §1.3); sem outra coincidência → descartado."""
    ctx = {
        "processo": "j5-8",
        "propostas": [
            {"licitante_cnpj": "11111111000100", "metadados": {"author": "Alfa Ltda"}},
            {"licitante_cnpj": "22222222000100", "metadados": {"author": "Beta Ltda"}},
        ],
        "_rubrica_erros": {"nivel": "erros_identicos_improvaveis"},  # SEM trecho
    }
    r = J5DigitaisCompartilhadas().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0
    assert r.valores["erros_textuais"] == "nao_avaliavel"


def test_j5_rubrica_ausente_sem_llm_nao_avaliavel_subjetivo():
    """Sem rubrica e sem LLM → componente subjetivo nao_avaliavel; coincidência objetiva (hash embutido) confirma."""
    ctx = {
        "processo": "j5-9",
        "propostas": [
            {"licitante_cnpj": "11111111000100", "hashes_embutidos": ["sha256:abc123def456"]},
            {"licitante_cnpj": "22222222000100", "hashes_embutidos": ["sha256:abc123def456"]},
        ],
    }
    r = J5DigitaisCompartilhadas().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["erros_textuais"] == "nao_avaliavel"
    assert r.valores["coincidencias"]["hash_embutido"]
