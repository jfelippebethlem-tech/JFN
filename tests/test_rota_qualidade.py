# -*- coding: utf-8 -*-
"""Rota do painel de conformidade (`/api/qualidade/conformidade`): INDISPONÍVEL ≠ zero, e a contagem por sistema
sai da fotografia dos sensores. Chama a função da rota direto (sem importar `server`); dados em `tmp_path`."""
from __future__ import annotations

import json

from rotas import qualidade as R


def _corpo(monkeypatch, dados):
    monkeypatch.setenv("JFN_DADOS", str(dados))
    return json.loads(R.api_qualidade_conformidade().body)


def _v(regra, sistema, chave, sev):
    return {"regra": regra, "sistema": sistema, "chave": chave, "titulo": f"t {chave}", "detalhe": "d",
            "acao_humana": "a", "sensor": "s", "severidade": sev, "titulo_regra": "tr"}


def test_sem_fotografia_e_indisponivel_nunca_zero(tmp_path, monkeypatch):
    d = _corpo(monkeypatch, tmp_path)
    assert d["estado"] == "INDISPONIVEL"
    assert d["total_violacoes"] is None and d["total_bloqueantes"] is None
    assert d["motivo"]
    assert all(s["violacoes_abertas"] is None and s["bloqueantes"] is None for s in d["sistemas"])


def test_fotografia_sintetica_conta_por_sistema(tmp_path, monkeypatch):
    viol = [_v("PAD-01", "painel", "a", "bloqueante"), _v("COR-04", "painel", "b", "alta"),
            _v("COR-04", "lex", "c", "media")]
    (tmp_path / "qualidade_estado.json").write_text(json.dumps(
        {"em": "2026-11-13T10:00:00", "violacoes": viol, "cegos": {"x": "OSError: sem arquivo"},
         "por_sistema": {"painel": 2, "lex": 1}, "por_regra": {"PAD-01": 1, "COR-04": 2},
         "total": 3, "bloqueantes": 1}), encoding="utf-8")
    d = _corpo(monkeypatch, tmp_path)
    assert d["estado"] == "MEDIDO" and d["medido_em"] == "2026-11-13T10:00:00"
    assert d["total_violacoes"] == 3 and d["total_bloqueantes"] == 1
    assert d["sensores_cegos"] == {"x": "OSError: sem arquivo"}
    s = {x["sistema"]: x for x in d["sistemas"]}
    assert (s["painel"]["violacoes_abertas"], s["painel"]["bloqueantes"]) == (2, 1)
    assert s["painel"]["regras_violadas"] == ["COR-04", "PAD-01"]
    assert s["painel"]["itens"][0]["severidade"] == "bloqueante"          # bloqueante primeiro
    assert (s["lex"]["violacoes_abertas"], s["lex"]["bloqueantes"]) == (1, 0)
    assert s["yoda"]["violacoes_abertas"] == 0                            # medido e limpo = 0 de verdade


def test_falha_de_leitura_vira_indisponivel(monkeypatch):
    from compliance_agent.qualidade import estado

    def _quebra(*a, **k):
        raise OSError("registro ilegível")
    monkeypatch.setattr(estado, "painel", _quebra)
    d = json.loads(R.api_qualidade_conformidade().body)
    assert d["ok"] is False and d["estado"] == "INDISPONIVEL"
    assert "total_violacoes" not in d                                      # nunca um zero inventado
