# -*- coding: utf-8 -*-
"""Segurança do painel: túnel não herda a isenção de localhost, login com limite, cabeçalhos."""
import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(server, "_DASH_SENHA", "senha-de-teste")
    monkeypatch.setattr(server, "_LOGIN_FALHAS", {})
    return TestClient(server.app)


def test_local_sem_proxy_passa_e_via_tunel_exige_login(cli):
    assert cli.get("/login_jfn").status_code == 200
    for h in ({"X-Forwarded-For": "203.0.113.9"}, {"Cf-Connecting-Ip": "203.0.113.9"},
              {"Tailscale-User-Login": "x@y"}):
        assert cli.get("/api/casos", headers=h).status_code == 401, h


def test_login_trava_depois_de_5_erros(cli):
    for _ in range(5):
        assert cli.post("/login_jfn", data={"senha": "errada"}, follow_redirects=False).status_code == 303
    assert cli.post("/login_jfn", data={"senha": "senha-de-teste"}, follow_redirects=False).status_code == 429


def test_login_certo_zera_e_senha_nao_ascii_nao_quebra(cli):
    assert cli.post("/login_jfn", data={"senha": "ção"}, follow_redirects=False).status_code == 303
    r = cli.post("/login_jfn", data={"senha": "senha-de-teste"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/painel"
    assert server._LOGIN_FALHAS == {}


def test_cabecalhos_de_seguranca(cli):
    r = cli.get("/login_jfn")
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
