# -*- coding: utf-8 -*-
"""Entrega dos arquivos do painel: mídia não passa pelo gzip; assets têm cache.

Medido em 04/11/2026: o portal-hero.mp4 (1.341.697 B) saía gzipado com 1.339.631 B — 0,15% de
ganho pago em CPU a cada visita — e a resposta 206 (Range) saía com `content-encoding: gzip` e um
`content-range` dos bytes NÃO comprimidos, o que quebra o player de vídeo que confia no Range.
"""
import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def cli():
    return TestClient(server.app)


def test_video_nao_e_gzipado_e_range_fica_integro(cli):
    h = {"Accept-Encoding": "gzip", "Range": "bytes=0-1023"}
    r = cli.get("/static/assets/portal-hero.mp4", headers=h)
    assert r.status_code == 206
    assert "content-encoding" not in r.headers
    assert len(r.content) == 1024


def test_js_continua_gzipado(cli):
    r = cli.get("/static/js/painel.bundle.js", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"


def test_assets_tem_cache(cli):
    r = cli.get("/static/assets/portal-hero.jpg")
    assert "max-age" in r.headers.get("cache-control", "")
    r = cli.get("/static/assets/jfn-icones.js?v=x")
    assert "immutable" in r.headers.get("cache-control", "")
