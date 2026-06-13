# -*- coding: utf-8 -*-
"""CRASH-PROOF do sweep SEI (regra do dono: *os sweeps não podem dar crash*).

O sweep dirige um browser Playwright; quando o browser/pipe MORRE (EPIPE/TargetClosed — aconteceu ao matar os
serviços antigos na cont.30, virando um Node.js crash não-tratado), o processo NÃO pode terminar com traceback.
Estes testes cobrem as duas linhas de defesa adicionadas em `tools/sei_sweep.py`:
  (1) `_browser_morto(exc)` — classifica morte-de-browser vs. erro pontual (conservador: na dúvida, False).
  (2) backstop de processo no `main()` — QUALQUER `Exception` que escape de `run()` vira log + saída limpa
      (sem crash), enquanto KeyboardInterrupt/SystemExit (BaseException) propagam normalmente.
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_sei_sweep_crashproof.py -q
"""
from __future__ import annotations

import sys

import pytest

from tools import sei_sweep


# ───────────────────────── _browser_morto: classificação ─────────────────────────
class _TargetClosedError(Exception):
    pass


@pytest.mark.parametrize("exc,esperado", [
    (_TargetClosedError("Target page, context or browser has been closed"), True),
    (Exception("write EPIPE"), True),
    (Exception("Connection closed while reading from the driver"), True),
    (Exception("Browser has been closed"), True),
    (Exception("pipe closed"), True),
    # erros pontuais / transitórios NÃO devem cortar a sessão (conservador → segue p/ o próximo processo):
    (ValueError("campo X inválido"), False),
    (Exception("Timeout 30000ms exceeded"), False),
    (KeyError("documentos"), False),
])
def test_browser_morto_classifica(exc, esperado):
    assert sei_sweep._browser_morto(exc) is esperado


# ───────────────────────── backstop do main(): nada crasha ─────────────────────────
def _silencia_log(monkeypatch):
    """Captura as linhas de _log em vez de escrever em disco/stdout durante o teste."""
    linhas: list[str] = []
    monkeypatch.setattr(sei_sweep, "_log", lambda m: linhas.append(m))
    return linhas


def test_main_engole_excecao_de_run(monkeypatch):
    """Se `run()` levanta uma Exception qualquer, o `main()` NÃO propaga (sai limpo + loga). Sem crash."""
    linhas = _silencia_log(monkeypatch)

    async def _run_que_explode(*a, **k):
        raise RuntimeError("write EPIPE — browser morreu no meio")

    monkeypatch.setattr(sei_sweep, "run", _run_que_explode)
    monkeypatch.setattr(sys, "argv", ["sei_sweep", "--max", "1"])

    # não deve levantar — o backstop converte em saída limpa
    sei_sweep.main()
    assert any("ABORTADO por erro não previsto" in ln and "sem crash" in ln for ln in linhas), linhas


def test_sigterm_seta_flag_de_parada(monkeypatch):
    """SIGTERM (o `timeout` do orquestrador) só LEVANTA a flag — o loop sai limpo entre processos e fecha o
    browser no finally (sem EPIPE). O handler nunca derruba o processo abruptamente."""
    monkeypatch.setattr(sei_sweep, "_PARAR", False)
    assert sei_sweep._PARAR is False
    sei_sweep._pedir_parada(15, None)  # 15 = SIGTERM
    assert sei_sweep._PARAR is True


def test_main_propaga_keyboardinterrupt(monkeypatch):
    """KeyboardInterrupt (BaseException) deve PROPAGAR — Ctrl-C/SIGINT encerra de verdade, não é 'crash a engolir'."""
    _silencia_log(monkeypatch)

    async def _run_interrompido(*a, **k):
        raise KeyboardInterrupt()

    monkeypatch.setattr(sei_sweep, "run", _run_interrompido)
    monkeypatch.setattr(sys, "argv", ["sei_sweep", "--max", "1"])

    with pytest.raises(KeyboardInterrupt):
        sei_sweep.main()
