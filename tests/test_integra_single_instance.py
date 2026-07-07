# -*- coding: utf-8 -*-
"""Single-instance da fila de íntegra: não roda 2 (evita 2 browsers)."""
import os
import subprocess
import sys
import tools.sei_integra_fila as F


def test_ja_rodando_ignora_o_proprio_pid(monkeypatch):
    class R:  # pgrep devolve só o próprio pid → NÃO é 'outra instância'
        stdout = f"{os.getpid()}\n"
    monkeypatch.setattr(F.subprocess, "run", lambda *a, **k: R())
    assert F._ja_rodando() is False


def test_ja_rodando_detecta_outra(monkeypatch):
    # PID precisa ser python VIVO: _ja_rodando valida /proc/pid/exe (fix bc403f6)
    outro = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        class R:
            stdout = f"{os.getpid()}\n{outro.pid}\n"
        monkeypatch.setattr(F.subprocess, "run", lambda *a, **k: R())
        assert F._ja_rodando() is True
    finally:
        outro.kill()
        outro.wait()
