# -*- coding: utf-8 -*-
"""T6 — enxame: síntese determinística com lentes injetadas."""
from compliance_agent.enxame import orquestrador as orq


def _lente(voto):
    return lambda dossie, gerar=None: {"voto": voto, "justificativa": "x", "citacao": "y"}


def test_sintese_mediana(monkeypatch):
    monkeypatch.setattr(orq, "LENTES", [("a", _lente(8)), ("b", _lente(9)), ("c", _lente(7)),
                                        ("refutador", _lente(6)), ("e", _lente(8))])
    r = orq.avaliar({"clausula": {}, "objeto": "x"})
    assert r["score_final"] == 8 and r["veredito"] == "direcionamento"


def test_empate_pende_pro_refutador(monkeypatch):
    monkeypatch.setattr(orq, "LENTES", [("a", _lente(5)), ("refutador", _lente(2))])
    r = orq.avaliar({"clausula": {}, "objeto": "x"})
    assert r["score_final"] <= 4   # desempate cético


def test_voto_invalido_nao_conta(monkeypatch):
    def _quebrado(dossie, gerar=None):
        return {"voto": None, "justificativa": "parse falhou", "citacao": ""}
    monkeypatch.setattr(orq, "LENTES", [("a", _lente(8)), ("b", _lente(8)), ("ruim", _quebrado)])
    r = orq.avaliar({"clausula": {}, "objeto": "x"})
    assert r["score_final"] == 8   # só os 2 válidos contam
