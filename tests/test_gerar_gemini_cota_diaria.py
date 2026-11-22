# -*- coding: utf-8 -*-
"""Par (chave, modelo) com a cota DIÁRIA estourada não é re-batido até a virada (meia-noite do Pacífico).

Medido em 22/11/2026 no `llm_trace.db` (7 dias): 86 mil das 92 mil tentativas Gemini eram 429 "PerDay" — cada
chamada re-tentava todas as chaves de todos os modelos já esgotados (~1,2 s cada) antes de achar um par vivo.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import compliance_agent.direcionamento_cerebro as DC
import compliance_agent.llm.free_llm as F

_DIA = ('{"error":{"details":[{"violations":[{"quotaMetric":"generativelanguage.googleapis.com/'
        'generate_content_free_tier_requests","quotaId":"GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}')
_MINUTO = ('{"error":{"details":[{"violations":[{"quotaMetric":"generativelanguage.googleapis.com/'
           'generate_content_free_tier_requests","quotaId":"GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}]}}')


class _Resp:
    def __init__(self, status, corpo=None, texto=""):
        self.status_code, self._c, self.text = status, corpo or {}, texto

    def json(self):
        return self._c

    def raise_for_status(self):
        return None


def _ok():
    return _Resp(200, {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}]})


def _preparar(monkeypatch, tmp_path, roteiro, chaves):
    posts = []

    class _Cliente:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, url, json=None, **_):
            mdl = url.split("/models/")[1].split(":")[0]
            posts.append((url.split("key=")[1], mdl))
            return roteiro[mdl]

    async def _sem_espera(_s):
        return None

    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(tmp_path / "trace.db"))
    monkeypatch.setattr(DC, "_gemini_keys", lambda: list(chaves))
    monkeypatch.setattr(DC, "_GEMINI_ESGOTADO", {})
    monkeypatch.setattr(DC, "_GEMINI_RR", 0)
    monkeypatch.setenv("DIRECIONAMENTO_GEMINI_MODELS", ",".join(roteiro))
    monkeypatch.delenv("DIRECIONAMENTO_GEMINI_MODEL", raising=False)
    monkeypatch.setattr(F, "cerebras_available", lambda: False)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _Cliente())
    monkeypatch.setattr(asyncio, "sleep", _sem_espera)
    return posts


def _chamar():
    return asyncio.run(DC.gerar_gemini([{"role": "user", "content": "oi"}]))


def test_par_esgotado_no_dia_nao_e_rebatido(monkeypatch, tmp_path):
    posts = _preparar(monkeypatch, tmp_path, {"a": _Resp(429, texto=_DIA), "b": _Resp(429, texto=_DIA), "c": _ok()},
                      ["k1", "k2"])
    assert _chamar() == "{}"
    antes = len(posts)
    # 1ª chamada: a 2, b 2, c 1 = 5 (antes da mudança eram 7: o 1º modelo tinha 2ª rodada após 3 s de espera,
    # re-batendo os pares que acabavam de dizer "cota do dia estourada")
    assert antes == 5
    posts.clear()
    for _ in range(10):
        assert _chamar() == "{}"
    # DEPOIS: só o par vivo é tentado — 1 requisição por chamada, sem a espera de 3 s do 1º modelo
    assert len(posts) == 10 and {m for _, m in posts} == {"c"}


def test_limite_por_minuto_continua_sendo_retentado(monkeypatch, tmp_path):
    """Só a cota DIÁRIA marca o par: 429 por minuto passa em segundos e o par segue no rodízio."""
    posts = _preparar(monkeypatch, tmp_path, {"a": _Resp(429, texto=_MINUTO), "c": _ok()}, ["k1"])
    _chamar()
    posts.clear()
    _chamar()
    assert ("k1", "a") in posts and DC._GEMINI_ESGOTADO == {}


def test_par_volta_depois_da_meia_noite_do_pacifico(monkeypatch, tmp_path):
    posts = _preparar(monkeypatch, tmp_path, {"a": _ok()}, ["k1"])
    DC._GEMINI_ESGOTADO[("k1", "a")] = 1.0          # prazo vencido
    assert _chamar() == "{}" and posts == [("k1", "a")]


def test_volta_da_cota_e_a_proxima_meia_noite_em_los_angeles():
    tz = ZoneInfo("America/Los_Angeles")
    agora = datetime(2026, 11, 21, 23, 30, tzinfo=tz).timestamp()
    assert DC._volta_da_cota_diaria(agora) == datetime(2026, 11, 22, 0, 0, tzinfo=tz).timestamp()
