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


def test_falha_preserva_o_ultimo_ok(tmp_path, monkeypatch):
    """A lacuna se mede do último SUCESSO: quatro falhas seguidas não podem apagar essa data."""
    monkeypatch.setattr(R, "ULTIMO", tmp_path / "ultimo.json")
    R.gravar_ultimo({"ok": True, "n": 983})
    ok = R.ultimo_ok_iso()
    for _ in range(4):
        R.gravar_ultimo({"ok": False, "erro": "navegador_ocupado"})
    assert R.ultimo_ok_iso() == ok


def test_verificador_cobre_a_lacuna():
    from datetime import datetime, timedelta, timezone
    agora = datetime(2026, 10, 24, 14, 30, tzinfo=timezone.utc)
    assert R.dias_a_verificar((agora - timedelta(hours=24)).isoformat(), agora) == [1, 2]   # rotina
    assert R.dias_a_verificar((agora - timedelta(days=5, hours=6)).isoformat(), agora) == [1, 2, 3, 4, 5, 6]
    assert R.dias_a_verificar((agora - timedelta(days=40)).isoformat(), agora) == list(range(1, 11))  # teto
    assert R.dias_a_verificar(None, agora) == [1, 2]
