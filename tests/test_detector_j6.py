# -*- coding: utf-8 -*-
"""Teste TARGETED do detector J6 (subcontratação cruzada / consórcio anômalo) — spec V2 do dono, §4/J6.

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO (dicts), LLM ausente OU rubrica pré-classificada
injetada (sem rede). Cobre: (a) confirma subcontratada que estava na lista de licitantes; (b) confirma consórcio
anômalo (consorciadas auto-suficientes); (c) descartado (subcontratada de especialidade real, fora dos
licitantes); (d) sem dados → nao_avaliavel; (e) cruzamento por RAIZ de CNPJ (filial de matriz que disputou).
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detector_j6.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS, ResultadoDetector
from compliance_agent.detectores.j6_subcontratacao_cruzada import J6SubcontratacaoCruzada


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


def test_j6_confirma_subcontratada_disputou_certame():
    """Subcontratada cujo CNPJ está na LISTA DE LICITANTES do mesmo certame → crítico (repartição do butim)."""
    ctx = {
        "processo": "j6-1",
        "licitantes": ["11111111000100", "22222222000100", "33333333000100"],
        "subcontratadas": [{"cnpj": "22222222000100", "objeto": "parte do fornecimento"}],
    }
    r = J6SubcontratacaoCruzada().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["critico"]
    assert "22222222000100" in r.valores["subcontratadas_que_disputaram"]
    assert r.evidencia


def test_j6_confirma_consorcio_anomalo():
    """≥2 consorciadas que atendiam SOZINHAS aos mínimos → consórcio desnecessário reunindo concorrentes → forte."""
    ctx = {
        "processo": "j6-2",
        "consorcio": [
            {"cnpj": "11111111000100", "atende_habilitacao_sozinha": True},
            {"cnpj": "22222222000100", "atende_habilitacao_sozinha": True},
            {"cnpj": "33333333000100", "atende_habilitacao_sozinha": False},
        ],
    }
    r = J6SubcontratacaoCruzada().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert len(r.valores["consorciadas_autossuficientes"]) == 2


def test_j6_confirma_certame_analogo_e_rubrica():
    """Subcontratada que disputou certame ANÁLOGO (forte) + rubrica sem-justificativa-técnica (forte)."""
    ctx = {
        "processo": "j6-3",
        "licitantes": ["11111111000100", "44444444000100"],
        "certames_relacionados": [["55555555000100", "66666666000100"]],
        "subcontratadas": [{"cnpj": "55555555000100", "objeto": "núcleo do objeto"}],
        "objeto_principal": "execução integral da obra",
        "_rubrica_subcontratacao": {"nivel": "sem_justificativa_tecnica", "trecho": "subcontrata o próprio núcleo"},
    }
    r = J6SubcontratacaoCruzada().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert "55555555000100" in r.valores["subcontratadas_em_certames_analogos"]
    assert r.valores["justificativa_subcontratacao"] == "sem_justificativa_tecnica"


def test_j6_descartado_especialidade_real_fora_dos_licitantes():
    """Subcontratada de especialidade real, FORA da lista de licitantes → lícito → descartado."""
    ctx = {
        "processo": "j6-4",
        "licitantes": ["11111111000100", "22222222000100"],
        "subcontratadas": [{"cnpj": "99999999000100", "objeto": "serviço de fundações especializadas"}],
        "objeto_principal": "obra civil",
    }
    r = J6SubcontratacaoCruzada().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0
    assert r.valores["subcontratadas_que_disputaram"] == []


def test_j6_descartado_consorcio_legitimo():
    """Consórcio onde NENHUMA consorciada atende sozinha aos mínimos → cooperação legítima → descartado."""
    ctx = {
        "processo": "j6-5",
        "consorcio": [
            {"cnpj": "11111111000100", "atende_habilitacao_sozinha": False},
            {"cnpj": "22222222000100", "atende_habilitacao_sozinha": False},
        ],
    }
    r = J6SubcontratacaoCruzada().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_j6_nao_avaliavel_sem_subcontratadas_nem_consorcio():
    """Sem `subcontratadas` E sem `consorcio` → nao_avaliavel (campo essencial ausente ≠ 0)."""
    ctx = {"processo": "j6-6", "licitantes": ["11111111000100", "22222222000100"]}
    r = J6SubcontratacaoCruzada().avaliar(ctx)
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.score == 0.0
    assert r.valores["tem_subcontratadas"] is False
    assert r.valores["tem_consorcio"] is False


def test_j6_cruzamento_por_raiz_de_cnpj():
    """Filial subcontratada (raiz 11111111) de MATRIZ que disputou (mesma raiz, sufixo diferente) → crítico."""
    ctx = {
        "processo": "j6-7",
        "licitantes": ["11111111000100", "22222222000100"],  # matriz 0001
        "subcontratadas": [{"cnpj": "11111111000299", "objeto": "parte do objeto"}],  # filial 0002, mesma raiz
    }
    r = J6SubcontratacaoCruzada().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["critico"]
    assert "11111111000299" in r.valores["subcontratadas_que_disputaram"]


def test_j6_cruzamento_por_qsa():
    """Subcontratada não-licitante MAS com sócio PJ (QSA) cujo CNPJ disputou → crítico (raiz via QSA)."""
    ctx = {
        "processo": "j6-8",
        "licitantes": ["11111111000100", "22222222000100"],
        "subcontratadas": [{
            "cnpj": "99999999000100",
            "objeto": "parte",
            "qsa": [{"cnpj_socio": "22222222000100"}],  # sócio PJ é um dos licitantes
        }],
    }
    r = J6SubcontratacaoCruzada().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["critico"]


def test_j6_rubrica_sem_llm_degrada_honesto():
    """Subcontratada cruzou (crítico objetivo) mas SEM LLM/rubrica → justificativa fica nao_avaliavel (honesto),
    o cruzamento objetivo permanece confirmado."""
    ctx = {
        "processo": "j6-9",
        "licitantes": ["11111111000100", "22222222000100"],
        "subcontratadas": [{"cnpj": "22222222000100", "objeto": "x"}],
    }
    r = J6SubcontratacaoCruzada().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.valores["justificativa_subcontratacao"] == "nao_avaliavel"
    assert r.score == ANCORAS["critico"]
