# -*- coding: utf-8 -*-
"""A rede de segurança de LLM não pode morrer com um erro que não aponta para nada.

Medido em 2026-08-03, ao tentar remedir a hermenêutica: o fallback do cérebro devolvia
`Groq falhou após retries: Illegal header value b'Bearer '`. A causa é dupla e nenhuma parte
dela é "o provedor caiu":

  1. `groq_agent.GROQ_API_KEY` era lido do ambiente **no import** — processo que sobe antes do
     `.env` ser carregado fica com a constante vazia para sempre (o `free_llm._groq_key()` já
     resolvia em tempo de execução justamente por isso; aqui a lição não tinha chegado);
  2. com a chave vazia o header vira `"Bearer "`, que o httpx recusa. O erro que chega ao log
     fala de cabeçalho, não de chave ausente — e o cooldown marca o Groq como fora do ar.

Resultado prático: o segundo provedor da rede de segurança some em silêncio, e a única pista é
uma mensagem sobre HTTP.
"""
import asyncio

import pytest

from compliance_agent.llm import groq_agent as G


def test_chave_e_resolvida_em_tempo_de_execucao(monkeypatch):
    """Chave posta no ambiente DEPOIS do import tem de valer."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_teste_123")
    assert G._chave() == "gsk_teste_123"


def test_sem_chave_o_erro_diz_o_que_falta(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(G, "GROQ_API_KEY", "")
    with pytest.raises(RuntimeError) as e:
        asyncio.run(G._groq([{"role": "user", "content": "oi"}]))
    msg = str(e.value)
    assert "GROQ_API_KEY" in msg, f"o erro continua sem apontar a causa: {msg}"
    assert "Illegal header" not in msg


def test_nao_gasta_retry_quando_a_chave_nao_existe(monkeypatch):
    """Três tentativas com backoff por causa de chave ausente é tempo jogado fora."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(G, "GROQ_API_KEY", "")
    dormiu = []
    monkeypatch.setattr(G.asyncio, "sleep", lambda s: dormiu.append(s) or asyncio.sleep(0))
    with pytest.raises(RuntimeError):
        asyncio.run(G._groq([{"role": "user", "content": "oi"}]))
    assert not dormiu, "esperou backoff para uma falha que nunca vai se resolver sozinha"
