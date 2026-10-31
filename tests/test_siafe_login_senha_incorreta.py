# -*- coding: utf-8 -*-
"""O login do SIAFE tem de NOMEAR "Usuário e/ou senha incorretos" e não insistir.

Medido em 30/10/2026 (sonda passiva, build 202609231239): o SIAFE 2 respondia "Erro — Usuário e/ou senha
incorretos." O clicador genérico fechava o aviso no "OK" e sobrava `login_falhou` mudo; o dreno e o retry
repetiam a senha errada ~20× no dia — insistir com senha errada é como uma conta se bloqueia.
"""
from __future__ import annotations

import asyncio

from compliance_agent import siafe_ob_orcamentaria as S
from tests.test_siafe_login_senha_expirada import _FORM, _PaginaSenhaExpirada

_ERRO = "\nErro\nUsuário e/ou senha incorretos.\nOK"


class _PaginaSenhaIncorreta(_PaginaSenhaExpirada):
    async def inner_text(self, _sel):
        return _FORM + (_ERRO if self.clicou_ok else "")


def _env(monkeypatch):
    monkeypatch.setenv("SIAFE_USER", "u")
    monkeypatch.setenv("SIAFE_PASS", "p")
    monkeypatch.setattr("compliance_agent.envfile.carregar_env", lambda: None)


def test_senha_incorreta_e_nomeada(monkeypatch):
    _env(monkeypatch)
    pg = _PaginaSenhaIncorreta()
    r = asyncio.run(S._login(pg, 2026))
    assert r["erro"] == "senha_incorreta" and "SIAFE_PASS" in r["detail"]
    assert pg.cliques_em_popup == 0


def test_credencial_recusada_nao_repete_o_login(monkeypatch):
    chamadas = []

    async def _login(pg, ex):
        chamadas.append(ex)
        return {"ok": False, "erro": "senha_incorreta"}
    monkeypatch.setattr(S, "_login", _login)

    class _Pg:
        async def wait_for_timeout(self, ms): raise AssertionError("não devia esperar para repetir")
    r = asyncio.run(S._login_e_navegar(_Pg(), 2026, tentativas=3))
    assert chamadas == [2026] and r["erros"] == ["senha_incorreta"]
