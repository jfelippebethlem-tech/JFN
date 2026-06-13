# -*- coding: utf-8 -*-
"""Auto-garantia do Chrome 9222 do Hermes.

Requisito do dono: "o Hermes tem que saber abrir o Chrome 9222 quando necessário". O Chrome 9222 é o
`chrome-jfn.service` (systemd user, Restart=always) — ponte CDP PERSISTENTE p/ coleta TFE/SIAFE ao vivo (NÃO é
leak, NÃO se fecha por idle: brigaria com o systemd). `_garantir_chrome()` é a rede de proteção: em qualquer
ação de browser (navegar_e_ler, ler_sei), se a porta 9222 não responde, (re)inicia o serviço canônico — sem
depender do LLM lembrar de 'abrir_chrome' e sem lançar um chrome concorrente. Testes mockam a porta (sem Chrome).
Rodar só este:  .venv/bin/python -m pytest tests/test_hermes_chrome_guard.py -q
"""
from __future__ import annotations

import asyncio

from compliance_agent import hermes_goal as hg


def test_garantir_chrome_noop_se_ja_no_ar(monkeypatch):
    """Idempotente: Chrome 9222 já no ar → no-op, não toca no systemd nem abre chrome concorrente."""
    chamou = {"systemctl": False, "abrir": False}

    async def _disp():
        return True

    async def _abrir():
        chamou["abrir"] = True
        return {"ok": True}

    monkeypatch.setattr(hg, "chrome_disponivel", _disp)
    monkeypatch.setattr(hg, "abrir_chrome_debug", _abrir)
    monkeypatch.setattr(hg.subprocess, "run", lambda *a, **k: chamou.__setitem__("systemctl", True))

    r = asyncio.run(hg._garantir_chrome())
    assert r.get("ja_estava") is True
    assert chamou["systemctl"] is False and chamou["abrir"] is False


def test_garantir_chrome_sobe_o_servico_quando_fora(monkeypatch):
    """Porta fora → (re)inicia o chrome-jfn.service (canônico), NÃO um chrome avulso."""
    chamadas = {"cmd": None}

    estados = iter([False, True])  # 1ª checagem: fora; depois do start: no ar

    async def _disp():
        try:
            return next(estados)
        except StopIteration:
            return True

    def _run(cmd, *a, **k):
        chamadas["cmd"] = cmd
        return None

    monkeypatch.setattr(hg, "chrome_disponivel", _disp)
    monkeypatch.setattr(hg.subprocess, "run", _run)

    r = asyncio.run(hg._garantir_chrome())
    assert chamadas["cmd"] == ["systemctl", "--user", "start", "chrome-jfn.service"]
    assert r.get("via") == "chrome-jfn.service"
