# -*- coding: utf-8 -*-
"""autoauditoria — fingerprint determinístico, drift e loop de sintonia (harness autoresearch)."""
from __future__ import annotations

import json

from tools import autoauditoria as AA


def test_drift_detecta_salto_de_volume():
    antes = {"fracionamento": {"n": 40, "top": ["a", "b", "c"]}}
    agora = {"fracionamento": {"n": 400, "top": ["a", "b", "c"]}}
    al = AA._drift(antes, agora)
    assert any(x["detector"] == "fracionamento" and x["tipo"] == "volume" for x in al)


def test_drift_ignora_variacao_pequena():
    antes = {"sobrepreco": {"n": 100, "top": list("abcdefghij")}}
    agora = {"sobrepreco": {"n": 103, "top": list("abcdefghij")}}
    assert AA._drift(antes, agora) == []


def test_drift_top_instavel():
    antes = {"radar_risco": {"n": 100, "top": list("abcdefghij")}}
    agora = {"radar_risco": {"n": 100, "top": list("abcdeVWXYZ")}}  # 5/10 trocaram
    al = AA._drift(antes, agora)
    assert any(x["tipo"] == "top_instavel" for x in al)


def test_drift_reporta_erro_de_detector():
    antes = {"conluio_qsa": {"n": 0, "top": []}}
    agora = {"conluio_qsa": {"erro": "no such table: pncp_resultado"}}
    al = AA._drift(antes, agora)
    assert any(x["tipo"] == "erro" for x in al)


def test_id_de_extrai_cnpj_aninhado():
    assert AA._id_de({"vencedor": {"cnpj": "11111111000111"}}) == "11111111000111"
    assert AA._id_de({"cnpj": "22222222000122"}) == "22222222000122"


def test_ler_programa_parseia_direcoes(tmp_path, monkeypatch):
    prog = tmp_path / "PROGRAMA.md"
    prog.write_text(
        "# titulo\n"
        "- sintonia: fracionamento min_colado 2 3 4\n"
        "prosa qualquer\n"
        "- sintonia: nepotismo max_raridade 12 20\n")
    monkeypatch.setattr(AA, "_PROGRAMA", prog)
    dirs = AA._ler_programa()
    assert len(dirs) == 2
    assert dirs[0] == {"detector": "fracionamento", "param": "min_colado", "grade": [2, 3, 4]}
    assert dirs[1]["grade"] == [12, 20]


def test_sintonizar_recomenda_mais_conservador(monkeypatch):
    # detector fake: n_achados cai com o threshold; testes sempre verdes
    def fake_chamar(fn, **kw):
        v = kw.get("min_colado", 0)
        return {"grupos": list(range(max(0, 10 - v)))}   # v=3→7, v=5→5
    monkeypatch.setattr(AA, "_chamar", fake_chamar)
    monkeypatch.setattr(AA, "_testes_verdes", lambda k: True)
    r = AA.sintonizar("fracionamento", "min_colado", [3, 4, 5])
    assert r["ok"] is True
    assert r["recomendado"]["valor"] == 5        # mais conservador (menos achados) e passa nos testes


def test_sintonizar_rejeita_valor_que_quebra_testes(monkeypatch):
    monkeypatch.setattr(AA, "_chamar", lambda fn, **kw: {"grupos": [1]})
    # só o valor 4 passa nos testes
    monkeypatch.setattr(AA, "_testes_verdes", lambda k: True)
    monkeypatch.setattr(AA, "sintonizar", AA.sintonizar)  # noop, clareza

    calls = {"v": None}

    def verdes(_k):
        return calls["v"] == 4
    # simula: cada experimento seta calls["v"] via _chamar
    def chamar(fn, **kw):
        calls["v"] = kw.get("min_colado")
        return {"grupos": [1, 2]}
    monkeypatch.setattr(AA, "_chamar", chamar)
    monkeypatch.setattr(AA, "_testes_verdes", verdes)
    r = AA.sintonizar("fracionamento", "min_colado", [3, 4, 5])
    verdes_exp = [e for e in r["experimentos"] if e.get("testes_verdes")]
    assert len(verdes_exp) == 1 and verdes_exp[0]["valor"] == 4
    assert r["recomendado"]["valor"] == 4


def test_baseline_grava_e_compara(tmp_path, monkeypatch):
    monkeypatch.setattr(AA, "_HIST", tmp_path)
    monkeypatch.setattr(AA, "fingerprint", lambda db_path=None: {"x": {"n": 10, "top": ["a"]}})
    r1 = AA.baseline(registrar=True)
    assert r1["drift"] == [] and r1["comparado_com"] is None       # 1ª noite: sem base
    monkeypatch.setattr(AA, "fingerprint", lambda db_path=None: {"x": {"n": 100, "top": ["z"]}})
    r2 = AA.baseline(registrar=True)
    assert any(a["tipo"] == "volume" for a in r2["drift"])         # 2ª noite: pegou o salto
    assert len(list(tmp_path.glob("fingerprint_*.json"))) == 2
