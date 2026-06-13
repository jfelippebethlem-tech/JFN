# -*- coding: utf-8 -*-
"""Guard de idle do browser Playwright no server.py (§6 — evita o leak de Chromium ocioso 24h numa VM sem swap).

O reaper encerra o browser após N min SEM uso e o `get_agent()` relança lazy. Estes testes exercitam a LÓGICA
de decisão do reaper SEM browser real (agente fake com `stop()` async), com o intervalo/limiar reduzidos:
  (a) ocioso além do limiar + lock livre  → fecha (stop() chamado, _agent vira None)
  (b) operação em andamento (lock preso)   → NÃO fecha (a operação segura o _agent_lock)
  (c) uso recente (dentro do limiar)        → NÃO fecha
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_browser_idle_guard.py -q
"""
from __future__ import annotations

import asyncio
import time

import pytest

import server


class _FakeAgent:
    def __init__(self) -> None:
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


async def _rodar_reaper_um_ciclo(timeout_s: float = 1.0) -> None:
    """Sobe o reaper como task, espera ele agir e cancela (shutdown limpo)."""
    task = asyncio.create_task(server._browser_idle_reaper())
    try:
        # o reaper dorme _BROWSER_REAP_INTERVAL antes de cada checagem; com intervalo minúsculo basta um instante
        await asyncio.sleep(timeout_s)
    finally:
        # cleanup tolerante: a task pode estar dormindo (cancela → CancelledError) OU já ter retornado
        # (guard desligado por idle_min=0) — ambos OK; só não queremos deixar a task vazando.
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.fixture(autouse=True)
def _restaura_estado():
    """Preserva e restaura os globais do server tocados pelos testes (não vazar entre testes/processos)."""
    salvos = (server._agent, server._browser_last_used, server._BROWSER_IDLE_MIN, server._BROWSER_REAP_INTERVAL)
    # acelera o reaper: checa a cada 20ms, limiar de ócio ~60ms
    server._BROWSER_REAP_INTERVAL = 0.02
    server._BROWSER_IDLE_MIN = 0.001  # 0.001 min = 60ms
    try:
        yield
    finally:
        (server._agent, server._browser_last_used, server._BROWSER_IDLE_MIN, server._BROWSER_REAP_INTERVAL) = salvos


def test_fecha_browser_ocioso():
    """(a) Ocioso além do limiar + lock livre → o reaper fecha e zera o singleton."""
    async def cenario():
        fake = _FakeAgent()
        server._agent = fake
        server._browser_last_used = time.monotonic() - 100  # muito antigo
        await _rodar_reaper_um_ciclo()
        assert fake.stopped is True, "stop() deveria ter sido chamado no browser ocioso"
        assert server._agent is None, "_agent deveria virar None p/ relançar lazy no próximo get_agent()"
    asyncio.run(cenario())


def test_nao_fecha_com_operacao_em_andamento():
    """(b) Lock preso (operação de browser rodando) → o reaper NÃO mexe, por mais ocioso que pareça o relógio."""
    async def cenario():
        fake = _FakeAgent()
        server._agent = fake
        server._browser_last_used = time.monotonic() - 100
        async with server._agent_lock:  # simula uma leitura SEI/SIAFE em andamento
            await _rodar_reaper_um_ciclo()
            assert fake.stopped is False, "não pode fechar o browser no meio de uma operação (lock preso)"
            assert server._agent is fake, "_agent deve permanecer durante a operação"
    asyncio.run(cenario())


def test_nao_fecha_uso_recente():
    """(c) Uso recente (dentro do limiar) → o reaper não fecha."""
    async def cenario():
        server._BROWSER_IDLE_MIN = 10.0  # limiar generoso (600s) p/ o uso "agora" ficar bem dentro dele
        fake = _FakeAgent()
        server._agent = fake
        server._browser_last_used = time.monotonic()  # agora mesmo
        await _rodar_reaper_um_ciclo(timeout_s=0.2)
        assert fake.stopped is False
        assert server._agent is fake
    asyncio.run(cenario())


def test_guard_desligado_quando_idle_min_zero():
    """`JFN_BROWSER_IDLE_MIN=0` desliga o guard: o reaper retorna na hora e nunca fecha."""
    async def cenario():
        server._BROWSER_IDLE_MIN = 0.0
        fake = _FakeAgent()
        server._agent = fake
        server._browser_last_used = time.monotonic() - 100
        await _rodar_reaper_um_ciclo(timeout_s=0.2)
        assert fake.stopped is False
        assert server._agent is fake
    asyncio.run(cenario())
