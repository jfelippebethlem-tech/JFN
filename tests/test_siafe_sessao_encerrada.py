# -*- coding: utf-8 -*-
"""A sessão do SIAFE tem de ser ENCERRADA ao fim de cada coleta, e o re-login após erro interno tem de esperar.

Medido em 28/10/2026: nenhum fluxo fazia logout — só fechava o navegador. A sessão seguia viva no servidor
("Sua sessão expira em: 29:49") e o par seguinte do dreno, ~4 min depois, recebia NullPointerException no
RootMenuParser em exercícios que logam normalmente (217200/2022, 254100/2020). O retry em 4 s só gastava as
três tentativas na mesma sessão presa.
"""
from __future__ import annotations

import asyncio

from playwright.async_api import Error as PWError

from compliance_agent import siafe_ob_orcamentaria as S


class _Pagina:
    def __init__(self, logado=True, logout_explode=False):
        self.logado, self.logout_explode, self.saiu, self.esperas = logado, logout_explode, False, []

    async def evaluate(self, js):
        if "a.xyo" in js:
            return self.logado
        if "'Sair'" in js:
            if self.logout_explode:
                raise PWError("Target page, context or browser has been closed")
            self.saiu = True

    async def wait_for_timeout(self, ms):
        self.esperas.append(ms)


class _Browser:
    fechado = False

    async def close(self):
        self.fechado = True


def test_encerrar_faz_logout_e_fecha():
    pg, b = _Pagina(), _Browser()
    asyncio.run(S._encerrar(pg, b))
    assert pg.saiu and b.fechado


def test_encerrar_sem_sessao_so_fecha():
    pg, b = _Pagina(logado=False), _Browser()
    asyncio.run(S._encerrar(pg, b))
    assert not pg.saiu and b.fechado


def test_logout_que_falha_nao_impede_fechar():
    pg, b = _Pagina(logout_explode=True), _Browser()
    asyncio.run(S._encerrar(pg, b))
    assert b.fechado


def test_toda_coleta_encerra_a_sessao():
    import inspect
    fonte = inspect.getsource(S)
    assert "finally:\n            await b.close()" not in fonte
    assert fonte.count("await _encerrar(pg, b)") >= 5


def test_relogin_apos_erro_interno_espera_240s(monkeypatch):
    async def _login(pg, ex):
        return {"ok": False, "erro": "erro_interno_siafe"}
    monkeypatch.setattr(S, "_login", _login)
    pg = _Pagina()
    r = asyncio.run(S._login_e_navegar(pg, 2022, tentativas=3))
    assert r["ultimo"]["erro"] == "erro_interno_siafe"
    assert pg.esperas == [240_000, 240_000]          # entre as tentativas, não depois da última


def test_relogin_outro_erro_segue_rapido(monkeypatch):
    async def _login(pg, ex):
        return {"ok": False, "erro": "login_falhou"}
    monkeypatch.setattr(S, "_login", _login)
    pg = _Pagina()
    asyncio.run(S._login_e_navegar(pg, 2022, tentativas=2))
    assert pg.esperas == [4000]


def test_tela_sem_campo_de_usuario_e_nomeada(monkeypatch):
    """28/10/2026 09:47: 'Page.fill: Timeout 30000ms' sem dizer o que havia na tela. Agora o login nomeia."""
    from playwright.async_api import TimeoutError as PwTimeout

    class _Tela(_Pagina):
        url = "https://www5.fazenda.rj.gov.br/SiafeRio/faces/errorDisplay.jsp"
        async def goto(self, *a, **k): pass
        async def wait_for_selector(self, *a, **k): raise PwTimeout("sem campo")
        async def inner_text(self, _s): return "Ocorreu um   erro\\n sessão"
    monkeypatch.setenv("SIAFE_USER", "u"); monkeypatch.setenv("SIAFE_PASS", "p")
    monkeypatch.setattr("compliance_agent.envfile.carregar_env", lambda: None)
    r = asyncio.run(S._login(_Tela(logado=False), 2022))
    assert r["erro"] == "tela_login_sem_campo" and "errorDisplay" in r["url"] and "Ocorreu" in r["detail"]


def test_tela_de_erro_no_login_tambem_espera_240s(monkeypatch):
    async def _login(pg, ex):
        return {"ok": False, "erro": "tela_login_sem_campo"}
    monkeypatch.setattr(S, "_login", _login)
    pg = _Pagina()
    asyncio.run(S._login_e_navegar(pg, 2020, tentativas=2))
    assert pg.esperas == [240_000]
