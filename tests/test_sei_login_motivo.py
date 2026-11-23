"""Login falho sem motivo não se investiga (22/11/2026, it-campo): 42 "LOGIN FALHOU" em 40 min, em todas as sessões,
e nenhuma linha dizia o que o SEI (ou a rede) respondeu — `login()` engolia o erro de cada tentativa. O motivo da
ÚLTIMA tentativa fica em `sei_reader.ULTIMA_FALHA_LOGIN`; o retorno (bool) não muda para os 17 chamadores."""
import asyncio

from playwright.async_api import Error as PWError

from tools import sei_reader as SR


class _PgSemRede:
    url = "chrome-error://chromewebdata/"

    async def goto(self, url, **kw):
        raise PWError("net::ERR_NAME_NOT_RESOLVED at https://sei.rj.gov.br/sip/login.php")

    async def wait_for_timeout(self, ms):
        pass


class _PgLoginRecusado:
    url = "https://sei.rj.gov.br/sip/login.php"

    class _R:
        status = 200

    async def goto(self, url, **kw):
        return self._R()

    async def evaluate(self, js, *a):
        if "txtUsuario" in js and "opts" in js:
            return {"user": True, "pwd": True, "opts": [{"v": "31", "t": "ITERJ"}]}
        if "innerText" in js:
            return "Usuário ou senha inválida."
        return None

    async def fill(self, *a, **k):
        pass

    async def select_option(self, *a, **k):
        pass

    async def title(self):
        return "SIP - Login"

    async def wait_for_timeout(self, ms):
        pass


def test_login_sem_rede_guarda_o_erro_de_navegacao():
    assert asyncio.run(SR.login(_PgSemRede(), tentativas=2)) is False
    assert "ERR_NAME_NOT_RESOLVED" in SR.ULTIMA_FALHA_LOGIN


def test_login_que_volta_ao_login_php_guarda_a_pagina():
    assert asyncio.run(SR.login(_PgLoginRecusado(), tentativas=2)) is False
    assert "login.php" in SR.ULTIMA_FALHA_LOGIN and "senha inválida" in SR.ULTIMA_FALHA_LOGIN
