# -*- coding: utf-8 -*-
"""Fila de arquivo GERAL (2026-07-03): todo o SEI, cdp bom não arquivado, ordenado por valor."""
import json
import tools.sei_integra_fila as F


def _cdp(cache, nome, numero, ndocs):
    (cache / f"cdp_{nome}.json").write_text(
        json.dumps({"numero": numero, "documentos": [1] * ndocs}), encoding="utf-8")


def test_fila_geral_ordena_por_valor_pula_vazio_e_arquivado(tmp_path, monkeypatch):
    cache = tmp_path / "cache"; cache.mkdir()
    arq = tmp_path / "arq"; arq.mkdir()
    monkeypatch.setattr(F, "CACHE", cache)
    monkeypatch.setattr(F, "ARQUIVO", arq)
    monkeypatch.setattr(F, "_valor_por_processo",
                        lambda: {"SEI-000001/000001/2024": 100.0, "SEI-000002/000002/2024": 500.0})
    _cdp(cache, "A", "SEI-000001/000001/2024", 3)   # bom, valor 100
    _cdp(cache, "B", "SEI-000002/000002/2024", 5)   # bom, valor 500 (deve vir 1º)
    _cdp(cache, "C", "SEI-000003/000003/2024", 0)   # docs=0 → fora
    # processo já arquivado COM conteúdo → fora
    _cdp(cache, "D", "SEI-000004/000004/2024", 2)
    txt = arq / "000004_000004_2024" / "texto"; txt.mkdir(parents=True)
    (txt / "001.txt").write_text("x")

    fila = F._fila_geral()
    seis = [e["sei"] for e in fila]
    assert seis == ["SEI-000002/000002/2024", "SEI-000001/000001/2024"]  # ordem por valor; C e D fora


def test_fila_geral_stub_nao_conta_como_arquivado(tmp_path, monkeypatch):
    cache = tmp_path / "cache"; cache.mkdir()
    arq = tmp_path / "arq"; arq.mkdir()
    monkeypatch.setattr(F, "CACHE", cache)
    monkeypatch.setattr(F, "ARQUIVO", arq)
    monkeypatch.setattr(F, "_valor_por_processo", lambda: {})
    _cdp(cache, "A", "SEI-000001/000001/2024", 2)
    # STUB: manifest sem texto/ → deve ENTRAR na fila (re-baixa)
    (arq / "000001_000001_2024").mkdir()
    (arq / "000001_000001_2024" / "manifest.json").write_text("{}")
    assert [e["sei"] for e in F._fila_geral()] == ["SEI-000001/000001/2024"]
