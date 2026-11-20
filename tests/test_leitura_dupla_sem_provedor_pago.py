# -*- coding: utf-8 -*-
"""A leitura dupla nunca chama provedor pago (§4.1 — nunca assumir free tier).

O Gemini está desligado por cobrança e o Cerebras saiu em 09/11. A cadeia antiga era
`setdefault("FREE_LLM_ONLY", "cerebras,zai,cohere,gemini")` — e uma lista que o filtro esvaziasse caía na cascata
inteira do `free_llm`, Gemini incluído. Agora a lista é fechada; sem gratuito disponível a leitura sai INDISPONÍVEL.
"""
from __future__ import annotations

import os

import tools.sei_leitura_dupla as M
from compliance_agent.llm import free_llm as F


def _sem_rede(monkeypatch, chamados):
    monkeypatch.setattr(F, "_em_cooldown", lambda p: False)
    monkeypatch.setattr(F, "_trace", lambda *a, **k: None)
    monkeypatch.setattr(F, "_marcar_cooldown", lambda *a, **k: None)
    monkeypatch.setattr(F, "gemini_chat", lambda *a, **k: chamados.append("gemini") or "{}")
    monkeypatch.setattr(F, "cerebras_chat", lambda *a, **k: chamados.append("cerebras") or "{}")
    monkeypatch.setattr(F, "best_free_chat", lambda *a, **k: chamados.append("cascata") or "{}")


def test_lista_fechada_sem_pagos():
    assert not ({"gemini", "cerebras"} & set(M._GRATIS_LEITURA))


def test_sem_gratuito_disponivel_sai_indisponivel_e_nao_chama_pago(monkeypatch):
    chamados: list[str] = []
    _sem_rede(monkeypatch, chamados)
    monkeypatch.setattr(F, "openrouter_available", lambda: False)
    monkeypatch.setattr(F, "extra_available", lambda p: False)
    monkeypatch.setenv("FREE_LLM_ONLY", "gemini")          # nem o ambiente reabre a porta
    monkeypatch.setattr(M, "_gerar_nous", lambda: None)
    r = M.extrair_interpretativo("texto do processo " * 50, "SEI-000000/000000/2026")
    assert r.get("estado") == "indisponivel"
    assert chamados == [], f"chamou provedor fora da lista: {chamados}"
    assert os.environ["FREE_LLM_ONLY"] == "gemini"         # a leitura não mexe no ambiente do processo


def test_usa_o_gratuito_da_lista(monkeypatch):
    chamados: list[str] = []
    _sem_rede(monkeypatch, chamados)
    monkeypatch.setattr(F, "openrouter_available", lambda: False)
    monkeypatch.setattr(F, "extra_available", lambda p: p == "cohere")
    monkeypatch.setattr(F, "extra_chat", lambda p, *a, **k: chamados.append(p) or '{"ok": 1}')
    assert M._gerar_cadeia_curta()("prompt", "sistema") == '{"ok": 1}'
    assert chamados == ["cohere"]
