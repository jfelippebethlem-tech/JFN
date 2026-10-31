# -*- coding: utf-8 -*-
"""Resposta CORTADA (finishReason MAX_TOKENS) não é resposta, e o raciocínio do 2.5 tem teto.

Medido em 29/10/2026: no gemini-2.5-flash o raciocínio conta dentro do maxOutputTokens (3.344 de
raciocínio + 604 de resposta num teto de 4.096). Quando passava, o JSON saía truncado e `gerar_gemini`
o devolvia como se fosse completo — 616 vereditos de lex_execucao nasceram vazios assim.
"""
from __future__ import annotations

import asyncio

import compliance_agent.direcionamento_cerebro as DC


class _Resp:
    status_code = 200

    def __init__(self, corpo):
        self._c = corpo

    def json(self):
        return self._c

    def raise_for_status(self):
        return None


class _Cliente:
    def __init__(self, roteiro, chamadas):
        self.roteiro, self.chamadas = roteiro, chamadas

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, url, json=None, **_):
        mdl = url.split("/models/")[1].split(":")[0]
        self.chamadas.append((mdl, json))
        fim, txt = self.roteiro[mdl]
        return _Resp({"candidates": [{"finishReason": fim, "content": {"parts": [{"text": txt}]}}]})


def _rodar(monkeypatch, roteiro):
    chamadas = []
    monkeypatch.setattr(DC, "_gemini_keys", lambda: ["k"])
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _Cliente(roteiro, chamadas))
    txt = asyncio.run(DC.gerar_gemini([{"role": "user", "content": "oi"}]))
    return txt, chamadas


def test_cortada_cai_para_o_proximo_modelo(monkeypatch):
    txt, ch = _rodar(monkeypatch, {"gemini-2.5-flash": ("MAX_TOKENS", '{"a": "pela met'),
                                   "gemini-2.0-flash": ("STOP", '{"a": 1}'),
                                   "gemini-2.5-flash-lite": ("STOP", '{"a": 2}')})
    assert txt == '{"a": 1}'
    assert [m for m, _ in ch] == ["gemini-2.5-flash", "gemini-2.0-flash"]


def test_teto_de_raciocinio_so_no_2_5(monkeypatch):
    _, ch = _rodar(monkeypatch, {"gemini-2.5-flash": ("MAX_TOKENS", "x"),
                                 "gemini-2.0-flash": ("STOP", "{}"), "gemini-2.5-flash-lite": ("STOP", "{}")})
    cfg = {m: b["generationConfig"] for m, b in ch}
    assert cfg["gemini-2.5-flash"]["thinkingConfig"] == {"thinkingBudget": 2048}
    assert "thinkingConfig" not in cfg["gemini-2.0-flash"]


def test_resposta_completa_segue_igual(monkeypatch):
    txt, ch = _rodar(monkeypatch, {"gemini-2.5-flash": ("STOP", '{"ok": true}'),
                                   "gemini-2.0-flash": ("STOP", "?"), "gemini-2.5-flash-lite": ("STOP", "?")})
    assert txt == '{"ok": true}' and len(ch) == 1
