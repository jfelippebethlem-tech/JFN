# -*- coding: utf-8 -*-
"""O login do SIAFE-2 tem de NOMEAR a senha expirada, não engoli-la.

Build 202609021528 (02/09/2026): após o "Ok", o SIAFE abre o popup "Senha Expirada — Sua senha
expirou. Por favor, informe uma nova senha." O clicador genérico de popups apertava "Ok" com os
campos vazios, o popup fechava e sobrava um `login_falhou` mudo — sete dias de coleta zero até
alguém abrir a screenshot. Trocar senha é ato do dono; o código só tem de dizer o motivo.
"""
from __future__ import annotations

import asyncio

import pytest

from compliance_agent import siafe_ob_orcamentaria as S

_FORM = "* Usuário\n* Senha\n* Exercício\nEsqueceu sua senha?\tOk\nVersão 4.169.6"
_POPUP = "\nSenha Expirada\nSua senha expirou. Por favor, informe uma nova senha.\n* Nova Senha\n* Confirmar Nova Senha\nOk\tCancelar"


class _PaginaSenhaExpirada:
    """Só o que `_login` toca; o popup aparece DEPOIS do clique em Ok e some se alguém clicar nele."""

    url = S.LOGIN_URL

    def __init__(self):
        self.clicou_ok = False
        self.cliques_em_popup = 0

    async def goto(self, *a, **k): pass
    async def wait_for_timeout(self, *a, **k): pass
    async def fill(self, *a, **k): pass
    async def select_option(self, *a, **k): pass
    async def screenshot(self, *a, **k): pass

    async def click(self, seletor, **k):
        if "btnConfirmar" in seletor:
            self.clicou_ok = True

    async def inner_text(self, _sel):
        return _FORM + (_POPUP if self.clicou_ok else "")

    async def evaluate(self, js):
        if "a.xyo" in js:                       # _logado / tem_workspace
            return False
        if "cbxExercicio" in js:                # exercício selecionado
            return "2026"
        if "itxSenhaAtual::content').value" in js:
            return 6                            # senha continua preenchida
        if "itxSenhaAtual::content')" in js:    # tem_senha_login
            return True
        if "myBtnConfirm" in js:                # clicador genérico de popups
            self.cliques_em_popup += 1
            return "Ok"
        return None


def test_senha_expirada_e_nomeada_e_nao_engolida(monkeypatch):
    monkeypatch.setenv("SIAFE_USER", "u")
    monkeypatch.setenv("SIAFE_PASS", "p")
    monkeypatch.setattr(S, "carregar_env", lambda: None, raising=False)
    pg = _PaginaSenhaExpirada()
    r = asyncio.run(S._login(pg, 2026))
    assert r["ok"] is False
    assert r["erro"] == "senha_expirada"
    assert "SIAFE_PASS" in r["detail"]
    # o motivo só é visível se ninguém fechou o popup antes de ler
    assert pg.cliques_em_popup == 0


def test_sem_popup_segue_para_login_falhou_como_antes(monkeypatch):
    monkeypatch.setenv("SIAFE_USER", "u")
    monkeypatch.setenv("SIAFE_PASS", "p")
    pg = _PaginaSenhaExpirada()
    monkeypatch.setattr(pg, "inner_text", lambda _s: asyncio.sleep(0, result=_FORM))
    r = asyncio.run(S._login(pg, 2026))
    assert r["ok"] is False and r["erro"] == "login_falhou"
