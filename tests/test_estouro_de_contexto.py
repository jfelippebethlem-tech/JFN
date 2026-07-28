# -*- coding: utf-8 -*-
"""Estouro de contexto: o provedor informa a contagem REAL — use-a em vez de chutar melhor.

MEDIDO em 2026-07-28. O planejamento usava `CHARS_POR_TOKEN = 3.5`. Num processo de faturas de
energia (tabela densa, números, espaçamento de PDF) o tokenizador real contou 1.036.551 tokens
onde a estimativa dizia 445.259 — razão de **1,50 char/token**, subestimativa de 2,3×. O lote
estourava a janela de 1.000.000 e o provedor devolvia 400.

Amostrando 36 processos do acervo, a razão vai de 2,42 a 3,79 pelo meu proxy — e o ponto medido
pela API foi 1,50, pior que o proxy. Ou seja: **não há constante que sirva**. O que serve é ler a
contagem verdadeira da mensagem de erro e refazer o corte com ela.
"""
from __future__ import annotations

from compliance_agent.llm.free_llm import estouro_de_contexto

_ERRO_OPENROUTER = (
    '{"error":{"message":"Provider returned error","code":400,"metadata":{"raw":"{\\"error\\":'
    '{\\"message\\":\\"This model\'s maximum context length is 1000000 tokens. However, your '
    'messages resulted in 1040739 tokens. Please reduce the length of the messages.\\",'
    '\\"type\\":\\"invalid_request_error\\"}}"}}}'
)


def test_extrai_limite_e_usado_da_mensagem_do_provedor():
    r = estouro_de_contexto(_ERRO_OPENROUTER)
    assert r == (1_000_000, 1_040_739)


def test_mensagem_de_outro_erro_devolve_None():
    assert estouro_de_contexto('{"error":{"message":"rate limit exceeded","code":429}}') is None


def test_texto_vazio_ou_nulo_nao_quebra():
    assert estouro_de_contexto("") is None
    assert estouro_de_contexto(None) is None


def test_variante_sem_escape_tambem_e_reconhecida():
    """A mesma mensagem chega crua quando o provedor não a aninha."""
    bruto = ("This model's maximum context length is 128000 tokens. However, your messages "
             "resulted in 131500 tokens.")
    assert estouro_de_contexto(bruto) == (128_000, 131_500)


def test_razao_real_permite_recalcular_o_corte():
    """O uso da informação: sabendo limite e usado, o fator de redução é aritmética simples."""
    limite, usado = estouro_de_contexto(_ERRO_OPENROUTER)
    fator = limite / usado
    assert 0.9 < fator < 1.0
    # Com margem, o próximo corte precisa ser menor que o fator bruto.
    assert fator * 0.85 < 0.85


def test_variante_you_requested_about(tmp_path=None):
    """2ª grafia, encontrada em 2026-07-28 num endpoint diferente do mesmo agregador:
    'you requested about N tokens' em vez de 'your messages resulted in N tokens'. Sem
    reconhecê-la, o lote não era subdividido — só marcado como falha e descartado."""
    bruto = ("This endpoint's maximum context length is 256000 tokens. However, you requested "
             "about 260344 tokens (256344 of text input, 4000 in the output).")
    assert estouro_de_contexto(bruto) == (256_000, 260_344)


def test_as_duas_grafias_convivem():
    a = estouro_de_contexto("maximum context length is 1000 tokens. However, your messages "
                            "resulted in 1200 tokens.")
    b = estouro_de_contexto("maximum context length is 1000 tokens. However, you requested "
                            "about 1200 tokens.")
    assert a == b == (1000, 1200)
