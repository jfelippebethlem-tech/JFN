# -*- coding: utf-8 -*-
"""Onda 1 — roteador adaptativo do Hermes: chat trivial fica no free default; caso difícil escala."""
from tools.hermes_model_router import escolher_modelo, DEFAULT, PESADO


def test_chat_trivial_fica_no_default_free():
    assert escolher_modelo("oi, tudo bem?") == DEFAULT
    assert escolher_modelo("bom dia") == DEFAULT


def test_caso_dificil_escala():
    assert escolher_modelo("faça um parecer jurídico sobre esse edital") == PESADO
    assert escolher_modelo("tem sobrepreço nesse contrato?") == PESADO
    assert escolher_modelo("monte um dossiê e investigue o cartel") == PESADO
    assert escolher_modelo("analise à luz da Lei 14.133") == PESADO


def test_mensagem_longa_escala():
    assert escolher_modelo("x" * 700) == PESADO


def test_forcar_pesado():
    assert escolher_modelo("oi", forcar_pesado=True) == PESADO


def test_bulk_repetitivo_usa_groq_free():
    """Bulk/lote → Groq instantâneo free (gemma2-9b-it DESCONTINUADO pelo Groq
    em 2026-06; sucessor llama-3.1-8b-instant). Nous = fallback do bulk."""
    from tools.hermes_model_router import escolher_modelo, BULK, BULK_FALLBACK
    assert BULK == ("groq", "llama-3.1-8b-instant")
    assert BULK_FALLBACK[0] == "nous"
    assert escolher_modelo("classifique esta noticia", tarefa="bulk") == BULK
    assert escolher_modelo("extraia campos", tarefa="lote") == BULK
    # sem tarefa=bulk, segue a regra normal (parecer -> pesado, nao bulk)
    assert escolher_modelo("parecer juridico") != BULK


def test_default_e_pesado_sao_so_modelos_FREE():
    """Invariante (Onda 0): o caminho automático usa SÓ modelos grátis (2.5-flash/flash-lite)."""
    from tools.hermes_model_router import DEFAULT, PESADO, PESADO_FALLBACK
    free = {"gemini-2.5-flash", "gemini-2.5-flash-lite"}
    assert DEFAULT[1] in free and PESADO[1] in free and PESADO_FALLBACK[1] in free


def test_modelo_melhor_NUNCA_automatico():
    """O modelo PAGO (gemini-2.5-pro) só sai com forcar_melhor=True (após o dono confirmar).
    A mera frase 'modelo melhor' NÃO troca sozinha — só sinaliza p/ o Yoda perguntar."""
    from tools.hermes_model_router import escolher_modelo, MELHOR, quer_modelo_melhor
    assert MELHOR[1] == "gemini-2.5-pro"
    # a frase é detectada (p/ o Yoda perguntar)...
    assert quer_modelo_melhor("usar o modelo melhor") is True
    assert quer_modelo_melhor("use o melhor modelo aqui") is True
    assert quer_modelo_melhor("bom dia") is False
    # ...mas NÃO escala sozinha (sem confirmação => fica no free)
    assert escolher_modelo("usar o modelo melhor") != MELHOR
    # só com a confirmação (forcar_melhor) usa o pago
    assert escolher_modelo("qualquer coisa", forcar_melhor=True) == MELHOR
