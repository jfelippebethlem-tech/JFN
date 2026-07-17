# -*- coding: utf-8 -*-
"""folha_estado (GESPERJ) — helpers determinísticos (sem rede)."""
from compliance_agent.collectors import folha_estado as FE


def test_cpf_middle6_padrao_gesperj():
    # máscara real da API: "***.889.157-**" → middle-6 no padrão do projeto
    assert FE._cpf_middle6("***.889.157-**") == "XX889157XXX"


def test_cpf_middle6_invalido_vazio():
    assert FE._cpf_middle6("") == ""
    assert FE._cpf_middle6(None) == ""
    assert FE._cpf_middle6("***.88.157-**") == ""  # 5 dígitos ≠ middle-6


def test_progresso_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(FE, "_PROGRESSO", tmp_path / "prog.json")
    FE._salvar_progresso("2026-06", 42)
    p = FE._carregar_progresso()
    assert p == {"competencia": "2026-06", "pagina": 42, "completa": False}
    FE._salvar_progresso("2026-06", 9641, completa=True)
    assert FE._carregar_progresso()["completa"] is True
    assert not (tmp_path / "prog.json.tmp").exists()  # write atômico não deixa lixo


def test_progresso_arquivo_corrompido(monkeypatch, tmp_path):
    p = tmp_path / "prog.json"
    p.write_text("{quebrado")
    monkeypatch.setattr(FE, "_PROGRESSO", p)
    assert FE._carregar_progresso() == {}
