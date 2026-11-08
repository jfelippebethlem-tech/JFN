# -*- coding: utf-8 -*-
"""Fonte SOB DEMANDA não pode viver em alarme — e alarme que nunca apaga é alarme desligado.

O DataJud/CNJ é consulta por número CNJ conhecido: não coleta em lote, não tem tabela no banco e
nunca teve `data/datajud_cron.log`. O SLO o classificava como `ausente` (⚠️) desde sempre, porque
mediu frescor de algo que não tem frescor. Medido em 2026-08-09, era o único ⚠️ permanente do
painel de pipelines — o tipo de ruído que faz o leitor parar de olhar a lista inteira.

A cura é declarar a natureza da fonte (`sob_demanda: true`), não fingir que ela está atrasada nem
criar um log falso para calá-la. E `sob_demanda` NÃO pode virar um jeito de esconder coleta
quebrada: o status é próprio, some da lista de ruins, e o teste abaixo garante que uma entrada
normal continua acusando.
"""
from __future__ import annotations

import tools.pipelines_slo as SLO


def _cfg(tmp_path, itens):
    import yaml
    p = tmp_path / "pipelines.yaml"
    p.write_text(yaml.safe_dump({"pipelines": itens}), encoding="utf-8")
    return p


def test_sob_demanda_nao_e_alarme(tmp_path, monkeypatch):
    monkeypatch.setattr(SLO, "CFG", _cfg(tmp_path, [
        {"nome": "datajud-cnj", "arquivo": "data/nao_existe.log", "max_stale_h": 720,
         "sob_demanda": True}]))
    monkeypatch.setattr(SLO, "BASE", tmp_path)
    r = SLO.checar()[0]
    assert r["status"] == "sob_demanda", f"fonte sob demanda ainda alarma como {r['status']}"
    assert r["status"] not in ("stale", "ausente")


def test_entrada_normal_sem_arquivo_continua_acusando(tmp_path, monkeypatch):
    """A porta que abri não pode virar tapete para coleta quebrada."""
    monkeypatch.setattr(SLO, "CFG", _cfg(tmp_path, [
        {"nome": "coleta-de-verdade", "arquivo": "data/nao_existe.log", "max_stale_h": 24}]))
    monkeypatch.setattr(SLO, "BASE", tmp_path)
    assert SLO.checar()[0]["status"] == "ausente"


def test_icone_existe_para_todo_status(tmp_path, monkeypatch):
    """Status novo sem ícone quebraria o relatório inteiro com KeyError no cron horário."""
    monkeypatch.setattr(SLO, "CFG", _cfg(tmp_path, [
        {"nome": "a", "arquivo": "x.log", "max_stale_h": 1, "sob_demanda": True},
        {"nome": "b", "arquivo": "x.log", "max_stale_h": 1},
    ]))
    monkeypatch.setattr(SLO, "BASE", tmp_path)
    import inspect
    fonte = inspect.getsource(SLO.main)
    for r in SLO.checar():
        assert f'"{r["status"]}":' in fonte, f"status {r['status']} sem ícone no relatório"
