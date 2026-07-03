# -*- coding: utf-8 -*-
"""Single-instance da fila de íntegra: não roda 2 (evita 2 browsers)."""
import os
import tools.sei_integra_fila as F


def test_ja_rodando_ignora_o_proprio_pid(monkeypatch):
    class R:  # pgrep devolve só o próprio pid → NÃO é 'outra instância'
        stdout = f"{os.getpid()}\n"
    monkeypatch.setattr(F.subprocess, "run", lambda *a, **k: R())
    assert F._ja_rodando() is False


def test_ja_rodando_detecta_outra(monkeypatch):
    class R:
        stdout = f"{os.getpid()}\n999999\n"
    monkeypatch.setattr(F.subprocess, "run", lambda *a, **k: R())
    assert F._ja_rodando() is True
