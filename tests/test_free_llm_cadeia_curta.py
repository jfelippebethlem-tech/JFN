# -*- coding: utf-8 -*-
"""Quando o 1º provedor está em 429, a CASCATA é que fica lenta — não o modelo.

Medido em 4 h de sweep do SEI (2026-08-13): com o cerebras devolvendo 429 cinquenta vezes (cota do
dia), cada leitura passava a percorrer os DOZE provedores em sequência, somando o timeout de todos.
Resultado: **437 chamadas, 54 sucessos (12%), 7,5 horas de espera acumulada**. Eu havia culpado o
modelo, o tamanho do prompt e o paralelismo antes de olhar para a cascata.

`FREE_LLM_ONLY` deixa quem faz VOLUME declarar a lista curta e falhar rápido, para tentar de novo
mais tarde. E nome desconhecido tem de AVISAR: o silêncio aqui foi o que fez `FREE_LLM_PREFER=nous`
— provedor que não existe na lista — parecer configuração válida, quando na verdade caía na ordem
padrão. O mesmo defeito do antigo default `qwen`.
"""
from __future__ import annotations

import importlib
import logging


def _ordem(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import compliance_agent.llm.free_llm as F
    importlib.reload(F)
    return F, F._get_provider_order()


def test_a_lista_curta_corta_a_cascata(monkeypatch):
    _, ordem = _ordem(monkeypatch, FREE_LLM_ONLY="cerebras,zai")
    assert ordem == ["cerebras", "zai"], "sem o corte, cada leitura paga o timeout dos doze"


def test_nome_que_nao_existe_AVISA_em_vez_de_sumir(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="compliance_agent.llm.free_llm")
    F, ordem = _ordem(monkeypatch, FREE_LLM_ONLY="cerebras,nao_existe")
    F._get_provider_order()          # a leitura do env acontece na chamada, não no import
    assert ordem == ["cerebras"]
    assert "nao_existe" in caplog.text, (
        "nome desconhecido sumindo em silêncio foi o que fez `FREE_LLM_PREFER=nous` parecer válido")


def test_sem_a_variavel_nada_muda(monkeypatch):
    """A cadeia curta é opt-in: quem não declara segue com a cascata completa de sempre."""
    monkeypatch.delenv("FREE_LLM_ONLY", raising=False)
    monkeypatch.delenv("FREE_LLM_PREFER", raising=False)
    _, ordem = _ordem(monkeypatch)
    assert len(ordem) > 10 and ordem[0] == "cerebras"
