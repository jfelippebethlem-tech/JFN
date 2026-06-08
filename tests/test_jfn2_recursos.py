# -*- coding: utf-8 -*-
"""Guarda de recurso (browser-lock + load-guard) — nunca crashar a VM por CPU."""
from __future__ import annotations

import os

from compliance_agent import recursos


def test_load_ok_limites(monkeypatch):
    monkeypatch.setattr(recursos, "n_cores", lambda: 2)
    monkeypatch.setattr(recursos, "load_atual", lambda: 1.0)
    assert recursos.load_ok(1.5) is True          # 1.0 <= 3.0
    monkeypatch.setattr(recursos, "load_atual", lambda: 5.0)
    assert recursos.load_ok(1.5) is False         # 5.0 > 3.0


def test_browser_lock_exclusivo(tmp_path, monkeypatch):
    monkeypatch.setattr(recursos, "_LOCK", tmp_path / "browser.lock")
    with recursos.browser_lock(espera_max=1, intervalo=0.1):
        assert recursos._LOCK.exists()
        # segundo lock NÃO entra enquanto o 1º está ativo (PID vivo = este processo)
        try:
            with recursos.browser_lock(espera_max=0.3, intervalo=0.1):
                assert False, "não deveria adquirir um 2º lock"
        except TimeoutError:
            pass
    assert not recursos._LOCK.exists()  # liberado no fim


def test_lock_orfao_e_quebrado(tmp_path, monkeypatch):
    monkeypatch.setattr(recursos, "_LOCK", tmp_path / "browser.lock")
    # lock de um PID que NÃO existe (órfão) → deve ser quebrado e readquirido
    (tmp_path / "browser.lock").write_text("999999999:0", encoding="utf-8")
    with recursos.browser_lock(espera_max=1, intervalo=0.1):
        # adquiriu apesar do lock órfão → agora o dono é este processo
        assert recursos._LOCK.read_text().startswith(str(os.getpid()))


def test_aguardar_load_timeout(monkeypatch):
    monkeypatch.setattr(recursos, "load_ok", lambda *_: False)  # nunca ok
    assert recursos.aguardar_load(espera_max=0.2, intervalo=0.1) is False
