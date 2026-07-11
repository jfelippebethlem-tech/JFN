# -*- coding: utf-8 -*-
"""Teste TARGETED do wiring de OCR em ``tools/sei_reader.py::_conteudo_doc``.

OFFLINE / STUBADO: sem browser, sem rede, sem DuckDB. Usa fakes simples do Playwright
(objetos com os métodos async que o helper chama) e faz monkeypatch de ``ocr_documento``.

Verifica:
1. Doc cujo ``innerText`` vem VAZIO (scan) → baixa bytes + chama OCR → conteúdo passa a ser
   o texto do OCR e o dict marca ``via == "ocr"`` (proveniência honesta).
2. Doc com texto HTML NORMAL (longo) → NÃO chama OCR (caminho que já funciona, intocado).
"""
import asyncio

import pytest

from tools import sei_reader


class _FakeResponse:
    def __init__(self, body=b"%PDF-1.4 fake", ok=True, content_type="application/pdf"):
        self._body = body
        self.ok = ok
        self.headers = {"content-type": content_type}

    async def body(self):
        return self._body


class _FakeRequest:
    def __init__(self, resp):
        self._resp = resp
        self.chamadas = []

    async def get(self, url, **kwargs):  # o reader passa timeout=...
        self.chamadas.append(url)
        return self._resp


class _FakeContext:
    def __init__(self, resp):
        self.request = _FakeRequest(resp)


class _FakePage:
    """Fake mínimo do Playwright Page para o helper ``_conteudo_doc``."""

    def __init__(self, inner_text, resp=None):
        self._inner_text = inner_text
        self.context = _FakeContext(resp or _FakeResponse())

    async def goto(self, url, **kwargs):
        return None

    async def wait_for_timeout(self, ms):
        return None

    async def evaluate(self, _js):
        return self._inner_text

    @property
    def frames(self):
        # o reader varre pg.frames (fix dos iframes 2026-07-10); o fake expõe a si mesmo como frame único
        return [self]


def test_innertext_vazio_dispara_ocr_e_marca_via(monkeypatch):
    chamou = {"ocr": 0}

    def fake_ocr(_body, *, tipo=None, lang="por"):
        chamou["ocr"] += 1
        assert tipo == "pdf"
        # >20 chars: o reader descarta OCR curto demais (guard anti-lixo)
        return "TEXTO OCR do documento digitalizado de teste"

    # patch no MÓDULO de onde o import lazy puxa a função.
    import compliance_agent.sei.ocr_docs as ocr_mod
    monkeypatch.setattr(ocr_mod, "ocr_documento", fake_ocr)

    pg = _FakePage(inner_text="", resp=_FakeResponse(content_type="application/pdf"))
    doc = {"url": "https://sei/doc/scan", "texto": "Documento Digitalizado"}

    res = asyncio.run(sei_reader._conteudo_doc(pg, doc))

    assert res is not None
    assert chamou["ocr"] == 1, "OCR deveria ter sido chamado para innerText vazio"
    assert "TEXTO OCR" in res["conteudo"]
    assert res.get("via") == "ocr"
    assert pg.context.request.chamadas == ["https://sei/doc/scan"]


def test_texto_html_normal_nao_chama_ocr(monkeypatch):
    chamou = {"ocr": 0}

    def fake_ocr(_body, *, tipo=None, lang="por"):
        chamou["ocr"] += 1
        return "NAO DEVERIA"

    import compliance_agent.sei.ocr_docs as ocr_mod
    monkeypatch.setattr(ocr_mod, "ocr_documento", fake_ocr)

    texto_html = "x" * 500  # > 50 chars → caminho nativo que já funciona
    # content-type de doc nativo do editor: a sonda de scan vê text/html e NÃO OCR'a
    pg = _FakePage(inner_text=texto_html,
                   resp=_FakeResponse(content_type="text/html; charset=iso-8859-1"))
    doc = {"url": "https://sei/doc/html", "texto": "Despacho"}

    res = asyncio.run(sei_reader._conteudo_doc(pg, doc))

    assert res is not None
    assert chamou["ocr"] == 0, "OCR NÃO deveria ser chamado quando há texto HTML nativo"
    assert res["conteudo"] == texto_html
    assert "via" not in res
    # a sonda de scan SEMPRE espia o content-type primeiro (o SEI mostra casca
    # >50 chars até para PDF-imagem) — 1 GET é esperado; OCR é que não pode rodar
    assert pg.context.request.chamadas == ["https://sei/doc/html"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
