# -*- coding: utf-8 -*-
"""Guard de idle + auto-abertura do Chrome 9222 do Hermes.

Requisito do dono: "o Hermes tem que saber abrir o Chrome 9222 quando necessário". O Chrome 9222 vivia ocioso
24h+ (mesmo leak do server.py). Solução: (1) `_garantir_chrome()` ABRE o Chrome sob demanda em QUALQUER ação de
browser (não depende do LLM lembrar de 'abrir_chrome'); (2) o idle-guard do server.py o fecha quando ocioso e o
Hermes reabre transparente. Estes testes cobrem a lógica SEM Chrome real (mock de chrome_disponivel/abrir/fechar).
Rodar só este:  .venv/bin/python -m pytest tests/test_hermes_chrome_guard.py -q
"""
from __future__ import annotations

import asyncio

import pytest

from compliance_agent import hermes_goal as hg


def test_chrome_ocioso_infinito_quando_nunca_usado(monkeypatch):
    """Sem uso registrado (_chrome_ultimo_uso=0), o ócio é infinito → o reaper fecha o Chrome leak na 1ª checagem."""
    monkeypatch.setattr(hg, "_chrome_ultimo_uso", 0.0)
    assert hg.chrome_ocioso_segundos() == float("inf")


def test_chrome_ocioso_pequeno_apos_uso(monkeypatch):
    """Após um uso recente, o ócio é pequeno (o reaper NÃO fecha durante missão ativa)."""
    import time
    monkeypatch.setattr(hg, "_chrome_ultimo_uso", time.monotonic())
    assert hg.chrome_ocioso_segundos() < 5


def test_garantir_chrome_abre_quando_fechado(monkeypatch):
    """_garantir_chrome ABRE o Chrome se a porta não responde — o Hermes não depende do LLM nem de pré-abertura."""
    chamou = {"abrir": False}

    async def _disp():
        return False

    async def _abrir():
        chamou["abrir"] = True
        return {"ok": True, "ja_estava": False}

    monkeypatch.setattr(hg, "chrome_disponivel", _disp)
    monkeypatch.setattr(hg, "abrir_chrome_debug", _abrir)
    monkeypatch.setattr(hg, "_chrome_ultimo_uso", 0.0)

    r = asyncio.run(hg._garantir_chrome())
    assert chamou["abrir"] is True, "deveria ter chamado abrir_chrome_debug com o Chrome fechado"
    assert r.get("ok") is True
    assert hg.chrome_ocioso_segundos() < 5, "uso deve ter sido marcado (timestamp atualizado)"


def test_garantir_chrome_nao_reabre_se_ja_no_ar(monkeypatch):
    """Idempotente: se o Chrome já está no ar, não reabre (não dispara processo à toa)."""
    chamou = {"abrir": False}

    async def _disp():
        return True

    async def _abrir():
        chamou["abrir"] = True
        return {"ok": True}

    monkeypatch.setattr(hg, "chrome_disponivel", _disp)
    monkeypatch.setattr(hg, "abrir_chrome_debug", _abrir)

    r = asyncio.run(hg._garantir_chrome())
    assert chamou["abrir"] is False
    assert r.get("ja_estava") is True


def test_fechar_chrome_idempotente_quando_ja_fechado(monkeypatch):
    """fechar_chrome_debug é idempotente: Chrome já fechado → ja_fechado=True, sem tentar matar nada."""
    async def _disp():
        return False

    monkeypatch.setattr(hg, "chrome_disponivel", _disp)
    r = asyncio.run(hg.fechar_chrome_debug())
    assert r.get("ok") is True and r.get("ja_fechado") is True
