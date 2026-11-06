# -*- coding: utf-8 -*-
"""/api/siafe/stats: 5 varreduras em 1,24 mi de linhas (3,5–11,7 s) — cache de 5 min, um cálculo por vez,
e resposta de ERRO nunca é guardada (senão um 500 passageiro ficaria 5 min no ar)."""
import json

from fastapi.responses import JSONResponse

import rotas.sistema as S


def test_segunda_chamada_vem_do_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(S, "_stats_cache", {})
    monkeypatch.setattr(S, "_calc_siafe_stats",
                        lambda: calls.append(1) or JSONResponse({"ok": True, "total": 7}))
    assert json.loads(S.api_siafe_stats().body)["total"] == 7
    assert json.loads(S.api_siafe_stats().body)["total"] == 7
    assert calls == [1]


def test_erro_nao_fica_no_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(S, "_stats_cache", {})
    monkeypatch.setattr(S, "_calc_siafe_stats",
                        lambda: calls.append(1) or JSONResponse({"ok": False}, status_code=500))
    S.api_siafe_stats()
    S.api_siafe_stats()
    assert calls == [1, 1]
