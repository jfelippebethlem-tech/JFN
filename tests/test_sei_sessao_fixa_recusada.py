# -*- coding: utf-8 -*-
"""Navegador FIXO com a sessão RECUSADA (it-campo, sessão s1, 19/11 22h → 20/11 14h: ~430 processos seguidos).

Medido em 20/11/2026 (reprodução dentro do browser_lock da s1, tela capturada): no contexto do navegador fixo da s1, o
`goto("https://sei.rj.gov.br/sei/")` de `ja_logado` parava NA PRÓPRIA URL `/sei/` com a página de rejeição da borda
("Web Page Blocked! … Attack ID: 20000008"). `ja_logado` só olhava a URL (começa com /sei/ e não é login.php) e
respondia True; ninguém relogava nem descartava os cookies, e TODO processo da sessão saía "SEM ÁRVORE" com "link
'Pesquisa' NÃO ESTÁ no DOM" em ~89 s. No mesmo navegador, mesmo IP, minuto seguinte, um contexto NOVO (cookies
limpos) logou e abriu os mesmos processos (616 e 15 documentos). O defeito era nosso: sessão dada por boa sem
olhar a página, e o pote de cookies do navegador fixo nunca renovado."""
from __future__ import annotations

import asyncio

import tools.sei_reader as SR

PAGINA_RECUSADA = ("block\nWeb Page Blocked!\n\nThe page cannot be displayed. Please contact the administrator for "
                   "additional information.\n\nURL: sei.rj.gov.br/sei/\n\nClient IP: 0.0.0.0\nAttack ID: 20000008\n"
                   "Message ID: 000000000000")


class _Ctx:
    def __init__(self):
        self.limpou = 0

    async def clear_cookies(self):
        self.limpou += 1


class _Pg:
    """URL final + se a página tem o menu do SEI (link 'Pesquisa') e o texto do corpo."""

    def __init__(self, url_final, menu: bool, corpo: str = "", titulo: str = ""):
        self.url, self._final, self._menu, self._corpo, self._titulo = "about:blank", url_final, menu, corpo, titulo
        self.context = _Ctx()

    async def goto(self, url, **kw):
        self.url = self._final

    async def wait_for_timeout(self, ms):
        pass

    async def title(self):
        return self._titulo

    async def evaluate(self, js, *a):
        if "document.body" in js:
            return self._corpo
        return self._menu          # _JS_TEM_LINK_PESQUISA / campo de protocolo


def test_pagina_de_rejeicao_na_url_do_sei_nao_e_sessao_valida():
    pg = _Pg("https://sei.rj.gov.br/sei/", menu=False, corpo=PAGINA_RECUSADA,
             titulo="The URL you requested has been blocked")
    assert not asyncio.run(SR.ja_logado(pg))


def test_desktop_do_sei_com_menu_e_sessao_valida():
    """Controle positivo: a URL do desktop E o menu pintado."""
    pg = _Pg("https://sei.rj.gov.br/sei/controlador.php?acao=procedimento_controlar", menu=True,
             corpo="GOVERNO DO ESTADO DO RIO DE JANEIRO\nPesquisa\nControle de Processos")
    assert asyncio.run(SR.ja_logado(pg))


def test_entrar_no_fixo_recusado_limpa_cookies_e_reloga(monkeypatch):
    logins = []

    async def login(pg, tentativas=40, orgao=None):
        logins.append(pg.context.limpou)       # quantas limpezas JÁ tinham acontecido quando o login começou
        return True

    monkeypatch.setattr(SR, "login", login)
    pg = _Pg("https://sei.rj.gov.br/sei/", menu=False, corpo=PAGINA_RECUSADA)
    assert asyncio.run(SR.entrar(pg, fixo=True, tentativas=3))
    assert logins == [1], "o login tem de começar com o pote de cookies do navegador fixo já limpo"


def test_entrar_no_fixo_valido_nao_reloga_nem_limpa(monkeypatch):
    """Controle negativo: sessão boa continua sem login novo (um login por sessão, não por processo)."""
    async def login(pg, tentativas=40, orgao=None):
        raise AssertionError("não devia relogar")

    monkeypatch.setattr(SR, "login", login)
    pg = _Pg("https://sei.rj.gov.br/sei/controlador.php?acao=procedimento_controlar", menu=True)
    assert asyncio.run(SR.entrar(pg, fixo=True))
    assert pg.context.limpou == 0


def test_entrar_sem_fixo_nao_mexe_em_cookies(monkeypatch):
    async def login(pg, tentativas=40, orgao=None):
        return True

    monkeypatch.setattr(SR, "login", login)
    pg = _Pg("x", menu=False)
    assert asyncio.run(SR.entrar(pg, fixo=False))
    assert pg.context.limpou == 0


def test_descricao_da_pagina_diz_o_que_estava_na_tela():
    pg = _Pg("https://sei.rj.gov.br/sei/", menu=False, corpo=PAGINA_RECUSADA,
             titulo="The URL you requested has been blocked")
    pg.url = pg._final
    d = asyncio.run(SR._descrever_pagina(pg))
    assert "sei.rj.gov.br/sei/" in d and "Web Page Blocked" in d
