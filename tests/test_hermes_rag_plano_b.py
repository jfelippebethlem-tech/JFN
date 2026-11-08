# -*- coding: utf-8 -*-
"""Cohere fora (429 da cota trial) não pode deixar o agente ~170 s em retry e SEM base: cai no lexical local."""
from __future__ import annotations

import json

import numpy as np

from tools import hermes_rag as R


def _corpus(tmp_path, monkeypatch):
    regs = [{"fonte": "a.md", "texto": "Disjuntor do dreno do SIAFE parou o login."},
            {"fonte": "b.md", "texto": "Receita de bolo de fubá com goiabada."}]
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps(r) for r in regs), encoding="utf-8")
    np.save(tmp_path / "e.npy", np.ones((2, 4), dtype="float32"))
    monkeypatch.setattr(R, "CHUNKS", tmp_path / "c.jsonl")
    monkeypatch.setattr(R, "EMB", tmp_path / "e.npy")
    monkeypatch.setitem(R._COHERE_FORA, "ate", 0.0)
    R._QEMB_CACHE.clear()


def test_cohere_recusou_cai_no_lexical_com_uma_tentativa(tmp_path, monkeypatch):
    _corpus(tmp_path, monkeypatch)
    chamadas = []

    def _embed(textos, tipo, tentativas=6, timeout=120):
        chamadas.append(tentativas)
        raise R.EmbedParcial("429", [])
    monkeypatch.setattr(R, "_embed", _embed)
    hits = R.consultar("login do SIAFE", 2)
    assert chamadas == [1]
    assert hits[0]["fonte"] == "a.md" and hits[0]["modo"] == "lexical"
    R.consultar("outra pergunta sobre dreno", 2)
    assert chamadas == [1]                       # disjuntor: 15 min sem bater de novo na Cohere


def test_ultimo_429_ainda_acusa_parcial(monkeypatch):
    class _R:
        status_code = 429
    monkeypatch.setattr("httpx.post", lambda *a, **k: _R())
    monkeypatch.setattr(R, "_key", lambda: "k")
    try:
        R._embed(["x"], "search_query", tentativas=1)
        assert False, "devia levantar EmbedParcial"
    except R.EmbedParcial:
        pass
