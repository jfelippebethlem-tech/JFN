# -*- coding: utf-8 -*-
"""Navegador FIXO por sessão (dono, 15/11/2026: "o it campo tá indo e vindo no SEI sem ser cuidadoso, apenas abrindo e
fechando tudo... faça direito" e "de um jeito que eu consiga usar o computador").

Antes: cada processo lançava um Chromium novo, logava e fechava — janelas piscando na tela do dono e um login por
processo no SEI. Agora, com SEI_CDP_URL, a captura conecta no navegador da sessão (aberto e logado), usa UMA aba e
fecha só a aba; login só quando a sessão do SEI expirou."""
from __future__ import annotations

import asyncio

import tools.sei_reader as SR


class _Pg:
    def __init__(self, url_final):
        self.url, self._final, self.fechada = "about:blank", url_final, False

    async def goto(self, url, **kw):
        self.url = self._final

    async def wait_for_timeout(self, ms):
        pass

    async def evaluate(self, js, *a):
        return True          # menu do SEI pintado (a página em si é testada em test_sei_sessao_fixa_recusada)

    async def close(self):
        self.fechada = True


class _Ctx:
    def __init__(self):
        self.rotas = []

    async def route(self, padrao, h):
        self.rotas.append(padrao)


class _B:
    def __init__(self):
        self.contexts, self.fechado = [_Ctx()], False

    async def close(self):
        self.fechado = True


class _Chromium:
    def __init__(self):
        self.cdp, self.lancou = None, False
        self.b = _B()

    async def connect_over_cdp(self, url, **kw):
        self.cdp = url
        return self.b

    async def launch(self, **kw):
        self.lancou = True
        return self.b


class _PW:
    def __init__(self):
        self.chromium = _Chromium()


def test_com_cdp_conecta_no_navegador_da_sessao_e_nao_lanca_outro(monkeypatch):
    monkeypatch.setenv("SEI_CDP_URL", "http://127.0.0.1:9301")
    pw = _PW()
    b, ctx, fixo = asyncio.run(SR.navegador_sei(pw))
    assert fixo and pw.chromium.cdp == "http://127.0.0.1:9301" and not pw.chromium.lancou
    assert ctx.rotas, "o corte do visualizador de PDF vale também no navegador fixo"


def test_fechar_no_navegador_fixo_fecha_so_a_aba(monkeypatch):
    b, pg = _B(), _Pg("x")
    asyncio.run(SR.fechar_sei(b, pg, fixo=True))
    assert pg.fechada and not b.fechado
    b2, pg2 = _B(), _Pg("x")
    asyncio.run(SR.fechar_sei(b2, pg2, fixo=False))
    assert b2.fechado


def test_ja_logado_pela_url_final():
    assert asyncio.run(SR.ja_logado(_Pg("https://sei.rj.gov.br/sei/controlador.php?acao=procedimento_controlar")))
    assert not asyncio.run(SR.ja_logado(_Pg("https://sei.rj.gov.br/sip/login.php?sigla_orgao_sistema=ERJ")))
    assert not asyncio.run(SR.ja_logado(_Pg("chrome-error://chromewebdata/")))


def test_limpeza_de_orfaos_preserva_o_navegador_fixo():
    import tools.itcampo_sei_paralelo as P
    import tools.vm_guard as G
    from pathlib import Path
    cmd = " ".join(P.comando_navegador(Path("/s/s1"), "integras", 1, "/x/chrome"))
    assert G.PRESERVE_FIXO in cmd
