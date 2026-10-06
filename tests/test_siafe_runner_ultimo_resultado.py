# -*- coding: utf-8 -*-
"""O LED de frescor do SIAFE tem de dizer POR QUE a coleta parou, não só QUANDO foi a última.

Entre 02 e 09/09/2026 a senha expirou e o painel mostrou apenas um LED envelhecendo. O runner
grava o último desfecho; o painel lê e troca o detalhe pelo motivo quando a última coleta falhou.
"""
from __future__ import annotations

from compliance_agent import siafe_runner as R


def test_falha_vira_motivo_no_led(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "ULTIMO", tmp_path / "ultimo.json")
    R.gravar_ultimo({"ok": False, "erro": "senha_expirada",
                     "detail": "SIAFE exige NOVA senha na tela de login."})
    d = R.detalhe_frescor("coletor diário 05:00")
    assert d.startswith("⛔")
    assert "senha_expirada" in d and "NOVA senha" in d and "coletor diário 05:00" in d


def test_sucesso_mantem_o_detalhe_base(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "ULTIMO", tmp_path / "ultimo.json")
    R.gravar_ultimo({"ok": True, "n": 412})
    assert R.detalhe_frescor("coletor diário 05:00") == "coletor diário 05:00"
    assert R.ultimo_resultado()["n"] == 412


def test_sem_arquivo_nao_quebra(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "ULTIMO", tmp_path / "nao_existe.json")
    assert R.ultimo_resultado() is None
    assert R.detalhe_frescor("base") == "base"
