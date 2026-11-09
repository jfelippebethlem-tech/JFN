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


_TUNEL = {"X-Forwarded-For": "203.0.113.9"}


def test_login_so_cita_o_que_o_visitante_da_internet_consegue_baixar():
    """A pagina de login e a UNICA que um visitante sem sessao ve — e ate 2026-11-09 ela citava
    `/static/assets/` (fundo e fontes), que para quem vem pelo tunel e 303. O login chegava sem fundo
    e sem fonte para todo mundo, menos para o localhost. Tudo o que ela cita tem de morar em
    `/static/login/`, e cada arquivo citado tem de existir no disco."""
    import re
    from pathlib import Path
    html = server._LOGIN_HTML
    citados = re.findall(r"/static/[A-Za-z0-9_./-]+", html)
    assert citados, "o login deixou de citar qualquer peca — o teste perdeu o objeto"
    fora = [c for c in citados if not c.startswith("/static/login/")]
    assert not fora, f"o login cita fora de /static/login/ (303 para quem vem da internet): {fora}"
    raiz = Path(server.__file__).resolve().parent
    faltam = [c for c in citados if re.search(r"\.[a-z0-9]+$", c) and not (raiz / c.lstrip("/")).exists()]
    assert not faltam, f"peca citada pelo login e ausente do disco: {faltam}"


def test_pecas_do_login_abrem_pelo_tunel_e_a_isencao_nao_alargou(cli):
    r = cli.get("/static/login/fonts/IBMPlexSans-Regular.woff2", headers=_TUNEL, follow_redirects=False)
    assert r.status_code == 200, r.status_code
    # a isencao continua sendo SO /static/login*: o resto do static segue atras do login
    for p in ("/static/assets/portal-hero.jpg", "/static/assets/fonts/IBMPlexSans-Regular.woff2",
              "/static/js/painel.bundle.js", "/painel"):
        assert cli.get(p, headers=_TUNEL, follow_redirects=False).status_code == 303, p
