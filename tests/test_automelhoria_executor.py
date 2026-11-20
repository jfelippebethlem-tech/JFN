# -*- coding: utf-8 -*-
"""Executor noturno: escolhe REINCIDIU antes de aberto, só áreas de código, e não repete item em 7 dias."""
from tools.automelhoria_executor import escolher, slug, _NEGADAS


def _it(a, area, st="aberto", p="2026-11-01"):
    return {"assinatura": a, "area": area, "status": st, "titulo": a, "primeiro": p}


def test_escolhe_reincidiu_e_area_de_codigo_e_nao_repete():
    fila = {x["assinatura"]: x for x in [
        _it("q:1", "qualidade"), _it("d:1", "detector"), _it("c:1", "catraca", "REINCIDIU"),
        _it("s:1", "systemd", "REINCIDIU"), _it("cur", "detector", "curado"), _it("d:2", "detector")]}
    out = [x["assinatura"] for x in escolher(fila, {}, 3, agora=1e9)]
    assert out == ["c:1", "d:1", "d:2"]
    out = [x["assinatura"] for x in escolher(fila, {"c:1": {"ts": 1e9 - 86400}}, 3, agora=1e9)]
    assert out == ["d:1", "d:2", "q:1"]


def test_nunca_push_e_slug():
    assert "Bash(git push:*)" in _NEGADAS
    assert slug("detector:fp:emendas_d3") == "detector-fp-emendas-d3"
