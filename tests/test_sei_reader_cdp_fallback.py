"""Navegador fixo que não responde ao CDP não mata a rodada: 3 tentativas e cai no navegador próprio (19/11/2026)."""
import asyncio

from playwright.async_api import Error as ErroPW

from tools import sei_reader as SR


class _Ctx:
    async def route(self, *a, **k):
        return None


class _Browser:
    contexts = [_Ctx()]

    async def new_context(self, **k):
        return _Ctx()


class _Chromium:
    def __init__(self, falhas):
        self.falhas, self.tentativas, self.lancou = falhas, 0, False

    async def connect_over_cdp(self, url, timeout=0):
        self.tentativas += 1
        if self.tentativas <= self.falhas:
            raise ErroPW("connect_over_cdp: Timeout 60000ms exceeded")
        return _Browser()

    async def launch(self, **k):
        self.lancou = True
        return _Browser()


class _PW:
    def __init__(self, falhas):
        self.chromium = _Chromium(falhas)


def _rodar(pw, monkeypatch):
    monkeypatch.setenv("SEI_CDP_URL", "http://127.0.0.1:9301")
    monkeypatch.setattr(SR, "sem_visualizador_pdf", lambda ctx: asyncio.sleep(0))
    _dormir = asyncio.sleep
    monkeypatch.setattr(SR.asyncio, "sleep", lambda s: _dormir(0))
    return asyncio.run(SR.navegador_sei(pw))


def test_conecta_na_segunda_tentativa(monkeypatch):
    pw = _PW(falhas=1)
    _b, _ctx, fixo = _rodar(pw, monkeypatch)
    assert fixo is True and pw.chromium.tentativas == 2 and not pw.chromium.lancou


def test_tres_falhas_caem_no_navegador_proprio(monkeypatch):
    pw = _PW(falhas=5)
    _b, _ctx, fixo = _rodar(pw, monkeypatch)
    assert fixo is False and pw.chromium.tentativas == 3 and pw.chromium.lancou
