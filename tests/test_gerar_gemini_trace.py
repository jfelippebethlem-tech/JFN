# -*- coding: utf-8 -*-
"""O caminho de LLM das perícias tem de aparecer no `llm_trace` — cada chamada HTTP, com modelo e tokens.

Medido em 11/11/2026: `llm_trace.db` tem `gemini`, `groq` e `openrouter` só até 14/08/2026. Desde então só o
`nous` grava. O `gerar_sync`/`gerar_gemini` de `direcionamento_cerebro` — que serve lex_execucao (~32/dia),
doc_juizo (~150 docs/dia) e bombeiros — não passava por `free_llm._trace`. Três meses de Gemini às cegas,
contra a §4.1 ("monitorar uso antes de sweep em volume"). Cada TENTATIVA HTTP é gravada (é ela que conta na
cota e, se houver billing, na fatura), não só o sucesso agregado.
"""
from __future__ import annotations

import asyncio
import sqlite3

import compliance_agent.direcionamento_cerebro as DC
import compliance_agent.llm.free_llm as F


class _Resp:
    def __init__(self, status, corpo, texto=""):
        self.status_code, self._c, self.text = status, corpo, texto

    def json(self):
        return self._c

    def raise_for_status(self):
        return None


class _Cliente:
    def __init__(self, roteiro):
        self.roteiro = roteiro

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def post(self, url, json=None, **_):
        return self.roteiro[url.split("/models/")[1].split(":")[0]]


def _linhas(db):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("select * from llm_trace order by rowid")]
    finally:
        con.close()


def _preparar(monkeypatch, tmp_path, roteiro):
    db = tmp_path / "trace.db"
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(db))
    monkeypatch.setattr(DC, "_gemini_keys", lambda: ["k"])
    monkeypatch.setenv("DIRECIONAMENTO_GEMINI_MODELS", ",".join(roteiro))
    monkeypatch.delenv("DIRECIONAMENTO_GEMINI_MODEL", raising=False)
    monkeypatch.setattr(F, "cerebras_available", lambda: False)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _Cliente(roteiro))
    return db


def _ok(txt, tin=120, tout=30, versao="gemini-3-flash-preview-0110"):
    return _Resp(200, {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": txt}]}}],
                       "usageMetadata": {"promptTokenCount": tin, "candidatesTokenCount": tout},
                       "modelVersion": versao})


def test_sucesso_grava_provedor_modelo_e_tokens(monkeypatch, tmp_path):
    db = _preparar(monkeypatch, tmp_path, {"m1": _ok('{"a":1}')})
    assert asyncio.run(DC.gerar_gemini([{"role": "user", "content": "oi"}])) == '{"a":1}'
    [r] = _linhas(db)
    assert (r["provedor"], r["ok"], r["modelo"], r["tokens_in"], r["tokens_out"]) == ("gemini", 1, "m1", 120, 30)
    assert DC.ultimo_modelo == "m1", "proveniência real para quem persiste o veredito"


def test_cada_tentativa_que_falha_tambem_conta(monkeypatch, tmp_path):
    """429 e 503 são requisições feitas — somem da medição se só o sucesso for gravado."""
    corpo_429 = '{"error":{"details":[{"violations":[{"quotaMetric":' \
                '"generativelanguage.googleapis.com/generate_content_free_tier_requests"}]}]}}'
    db = _preparar(monkeypatch, tmp_path, {"a": _Resp(503, {}), "b": _Resp(429, {}, corpo_429),
                                           "c": _ok("{}")})
    asyncio.run(DC.gerar_gemini([{"role": "user", "content": "oi"}]))
    rs = _linhas(db)
    assert [(r["modelo"], r["ok"]) for r in rs] == [("a", 0), ("b", 0), ("c", 1)]
    assert rs[0]["erro"].startswith("503")
    # a métrica de cota do 429 é a evidência do TIER (free_tier_requests ≠ conta paga) — tem de ficar no trace
    assert "free_tier" in rs[1]["erro"]


def test_trace_antigo_sem_colunas_novas_e_migrado(monkeypatch, tmp_path):
    """O `llm_trace.db` de produção tem só (ts, provedor, ok, ms, erro): a coluna nova entra sem perder linha."""
    db = tmp_path / "trace.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE llm_trace(ts TEXT DEFAULT (datetime('now')), provedor TEXT, ok INT, ms INT, erro TEXT)")
    con.execute("INSERT INTO llm_trace(provedor, ok, ms, erro) VALUES('nous',1,10,'')")
    con.commit()
    con.close()
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(db))
    F._trace("gemini", True, 5, modelo="m", tokens_in=1, tokens_out=2)
    rs = _linhas(db)
    assert len(rs) == 2 and rs[1]["modelo"] == "m" and rs[0]["modelo"] is None


def test_fallback_do_gerar_default_tambem_grava(monkeypatch, tmp_path):
    """Gemini fora → groq responde: o groq tem de aparecer no trace (sumiu desde 14/08)."""
    db = tmp_path / "trace.db"
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(db))
    monkeypatch.setattr(DC, "_gemini_keys", lambda: [])

    async def _groq(_m):
        return "{}"

    monkeypatch.setattr(DC, "_groq_gerar", _groq)
    monkeypatch.setattr(F, "_em_cooldown", lambda p: False)
    assert asyncio.run(DC._gerar_default([{"role": "user", "content": "x"}])) == "{}"
    assert [(r["provedor"], r["ok"]) for r in _linhas(db)] == [("groq", 1)]
