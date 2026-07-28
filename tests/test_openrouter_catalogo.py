# -*- coding: utf-8 -*-
"""Catálogo vivo de modelos `:free` — a trava contra o literal que apodrece.

Em 2026-07-28, 5 dos 6 ids de modelo fixados no código estavam mortos, e o sintoma era um 404
tratado como erro transitório: 33 s de backoff por chamada para reencontrar o mesmo 404. O
Hermes tinha a lista INTEIRA morta e caía para Groq sem que nada dissesse por quê.

Estes testes protegem as três decisões que impedem a repetição: capacidade não é contexto,
catálogo indisponível não é catálogo vazio, e o óbito observado no uso real realimenta a escolha.

Nada aqui vai à rede.
"""
from __future__ import annotations

import json

import pytest

from compliance_agent.llm import openrouter_catalogo as C


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CACHE", tmp_path / "free.json")
    monkeypatch.setattr(C, "RANKING", tmp_path / "ranking.json")
    return tmp_path


def _semear(monkeypatch, modelos):
    monkeypatch.setattr(C, "_buscar", lambda: modelos)


_FROTA = [
    {"id": "nvidia/nemotron-3-ultra-550b-a55b:free", "ctx": 1_000_000, "modalidades": ["text"]},
    {"id": "google/gemma-4-31b-it:free", "ctx": 262_144, "modalidades": ["image", "text"]},
    {"id": "google/gemma-4-26b-a4b-it:free", "ctx": 262_144, "modalidades": ["image", "text"]},
    {"id": "nvidia/nemotron-3-nano-30b-a3b-reasoning:free", "ctx": 256_000,
     "modalidades": ["text"]},
    {"id": "cohere/north-mini-code:free", "ctx": 256_000, "modalidades": ["text"]},
    {"id": "nvidia/nemotron-3.5-content-safety:free", "ctx": 128_000, "modalidades": ["text"]},
]


# ── capacidade ≠ contexto ─────────────────────────────────────────────────────────────────

def test_documento_recusa_modelo_pequeno_por_maior_que_seja_a_janela(isolar, monkeypatch):
    """O erro que este piso existe para impedir: 26B com 262k de contexto lê o processo
    inteiro e o interpreta mal. Janela grande é quanto CABE, não quanto ENTENDE."""
    _semear(monkeypatch, [m for m in _FROTA if "gemma" in m["id"]])
    assert C.escolher("documento") is None, "nenhum gemma atinge o piso de capacidade"


def test_documento_escolhe_o_maior_quando_ha_um_capaz(isolar, monkeypatch):
    _semear(monkeypatch, _FROTA)
    assert C.escolher("documento") == "nvidia/nemotron-3-ultra-550b-a55b:free"


def test_id_que_nao_declara_tamanho_nao_entra_em_documento_por_suposicao(isolar, monkeypatch):
    _semear(monkeypatch, [{"id": "poolside/laguna-m.1:free", "ctx": 262_144,
                           "modalidades": ["text"]}])
    assert C.escolher("documento") is None


@pytest.mark.parametrize("mid,esperado", [
    ("nvidia/nemotron-3-ultra-550b-a55b:free", 550.0),   # MoE: total, não os ativos
    ("google/gemma-4-31b-it:free", 31.0),
    ("nvidia/nemotron-nano-9b-v2:free", 9.0),
    ("poolside/laguna-m.1:free", 0.0),
])
def test_le_o_tamanho_do_proprio_id(mid, esperado):
    assert C._params_b(mid) == esperado


# ── saída limpa ───────────────────────────────────────────────────────────────────────────

def test_fast_exclui_modelo_que_vaza_raciocinio(isolar, monkeypatch):
    """Medido: um `reasoning` respondeu 'responda somente OK' com o próprio monólogo interno.
    Rubrica fechada morre com isso."""
    _semear(monkeypatch, [m for m in _FROTA if "reasoning" in m["id"]])
    assert C.escolher("fast") is None


def test_modelo_de_guarda_nunca_entra_como_chat(isolar, monkeypatch):
    _semear(monkeypatch, [m for m in _FROTA if "content-safety" in m["id"]])
    assert all(C.escolher(p) is None for p in C.PERFIS)


def test_visao_exige_modalidade_de_imagem(isolar, monkeypatch):
    _semear(monkeypatch, _FROTA)
    assert C.escolher("visao") == "google/gemma-4-31b-it:free"


def test_coder_prefere_modelo_de_codigo(isolar, monkeypatch):
    _semear(monkeypatch, _FROTA)
    assert C.escolher("coder") == "cohere/north-mini-code:free"


def test_perfil_invalido_falha_alto(isolar, monkeypatch):
    with pytest.raises(ValueError, match="perfil inválido"):
        C.escolher("turbinado")


# ── medição vence heurística ──────────────────────────────────────────────────────────────

def test_nota_medida_supera_o_tamanho_declarado(isolar, monkeypatch):
    """O ponto do banco de provas: se o 550B se sai mal no NOSSO domínio e outro se sai bem,
    manda a medição — tamanho é estimativa, nota é observação."""
    _semear(monkeypatch, _FROTA)
    grande = {"id": "nvidia/nemotron-3-super-120b-a12b:free", "ctx": 262_144,
              "modalidades": ["text"]}
    _semear(monkeypatch, _FROTA + [grande])
    (isolar / "ranking.json").write_text(json.dumps({"notas": {grande["id"]: 95.0}}))
    assert C.escolher("documento") == grande["id"]


# ── indisponível ≠ vazio ──────────────────────────────────────────────────────────────────

def test_catalogo_fora_do_ar_usa_o_cache_antigo(isolar, monkeypatch):
    """Catálogo velho é muito melhor que nenhum. O que não se faz é voltar ao literal."""
    _semear(monkeypatch, _FROTA)
    assert C.escolher("documento")
    monkeypatch.setattr(C, "_buscar", lambda: None)
    monkeypatch.setattr(C, "TTL_S", 0)                    # força a revalidação
    assert C.escolher("documento") == "nvidia/nemotron-3-ultra-550b-a55b:free"


def test_sem_cache_e_sem_rede_devolve_None_e_nao_um_chute(isolar, monkeypatch):
    """`None` é 'não sei', não 'não existe' — quem chama pula o provedor, não o mata."""
    monkeypatch.setattr(C, "_buscar", lambda: None)
    assert C.escolher("fast") is None
    assert C.catalogo() == []


def test_cache_corrompido_nao_quebra(isolar, monkeypatch):
    (isolar / "free.json").write_text("{ não é json")
    _semear(monkeypatch, _FROTA)
    assert C.escolher("fast")


# ── o mundo real realimenta a escolha ─────────────────────────────────────────────────────

def test_modelo_que_deu_404_no_uso_real_sai_da_escolha(isolar, monkeypatch):
    _semear(monkeypatch, _FROTA)
    primeiro = C.escolher("documento")
    C.marcar_morto(primeiro)
    assert C.escolher("documento") != primeiro


def test_obito_expira_para_o_modelo_poder_voltar(isolar, monkeypatch):
    """Banir para sempre é tão errado quanto não banir: o provedor recoloca modelos."""
    _semear(monkeypatch, _FROTA)
    alvo = C.escolher("documento")
    C.marcar_morto(alvo)
    monkeypatch.setattr(C, "TTL_S", 0)
    assert C.escolher("documento") == alvo


def test_marcar_morto_nao_apaga_o_catalogo(isolar, monkeypatch):
    _semear(monkeypatch, _FROTA)
    C.catalogo()
    C.marcar_morto("qualquer/coisa:free")
    monkeypatch.setattr(C, "_buscar", lambda: None)
    assert len(C.catalogo()) == len(_FROTA)
