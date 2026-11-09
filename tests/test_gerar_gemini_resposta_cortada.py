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
    # a mecânica do corte independe de QUAIS modelos estão na cascata — fixo a lista que o teste roteiriza
    monkeypatch.setenv("DIRECIONAMENTO_GEMINI_MODELS", ",".join(roteiro))
    monkeypatch.delenv("DIRECIONAMENTO_GEMINI_MODEL", raising=False)
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


class _Resp503(_Resp):
    status_code = 503


def test_503_do_modelo_pula_para_o_proximo_sem_varrer_as_chaves(monkeypatch):
    """09/11/2026: gemini-3.6-flash deu 503 'alta demanda' nas 8 chaves, uma por uma — 45 s perdidos.
    503 é do MODELO, não da chave: tem que ir direto para o próximo modelo."""
    chamadas = []

    class _C(_Cliente):
        async def post(self, url, json=None, **_):
            mdl = url.split("/models/")[1].split(":")[0]
            chamadas.append(mdl)
            if mdl == "a":
                return _Resp503({})
            return _Resp({"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}]})

    monkeypatch.setattr(DC, "_gemini_keys", lambda: ["k1", "k2", "k3", "k4"])
    monkeypatch.setenv("DIRECIONAMENTO_GEMINI_MODELS", "a,b")
    monkeypatch.delenv("DIRECIONAMENTO_GEMINI_MODEL", raising=False)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _C({}, []))
    assert asyncio.run(DC.gerar_gemini([{"role": "user", "content": "oi"}])) == "{}"
    assert chamadas == ["a", "b"]


def test_cascata_padrao_sem_modelo_morto_nem_lite(monkeypatch):
    """gemini-2.0-flash não existe mais; flash-lite errou o jurídico — nenhum dos dois no parecer."""
    vistos = []

    class _C(_Cliente):
        async def post(self, url, json=None, **_):
            vistos.append(url.split("/models/")[1].split(":")[0])
            return _Resp({"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": ""}]}}]})

    monkeypatch.setattr(DC, "_gemini_keys", lambda: ["k"])
    monkeypatch.delenv("DIRECIONAMENTO_GEMINI_MODELS", raising=False)
    monkeypatch.delenv("DIRECIONAMENTO_GEMINI_MODEL", raising=False)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _C({}, []))
    import compliance_agent.llm.free_llm as F
    monkeypatch.setattr(F, "cerebras_available", lambda: False)
    try:
        asyncio.run(DC.gerar_gemini([{"role": "user", "content": "oi"}]))
    except RuntimeError:
        pass
    assert vistos[0] == "gemini-3-flash-preview"
    assert "gemini-2.0-flash" not in vistos and not any("lite" in m for m in vistos)
