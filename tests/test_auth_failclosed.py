# -*- coding: utf-8 -*-
"""Painel falha-fechado (plano mestre v2, O0.3 / §3.11).

- produção sem senha, com senha curta, secret fraco/igual à senha ou sem COOKIE_SECURE → o boot aborta;
- não há mais "sem senha = gate desligado";
- localhost é SÓ 127.0.0.1/::1 e sem cabeçalho de proxy; `client=None` não é localhost;
- token carrega o epoch de revogação (trocar JFN_DASH_EPOCH derruba todas as sessões);
- rate limit do login persiste em SQLite (sobrevive a restart);
- modo manutenção: leitura passa, escrita → 503 {"manutencao": true}, HTML leva a faixa.
"""
import asyncio
import json
import sys

import pytest
from fastapi.testclient import TestClient

import server

_SENHA = "s" * 24
_SECRET = "k" * 48
_PROD_OK = {"JFN_ENV": "producao", "JFN_DASH_PASSWORD": _SENHA, "JFN_DASH_SECRET": _SECRET,
            "COOKIE_SECURE": "1"}


@pytest.fixture
def cli(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "_DASH_SENHA", "senha-de-teste")
    monkeypatch.setattr(server, "_RATELIMIT_DB", tmp_path / "auth_ratelimit.db")
    monkeypatch.setattr(server, "_MANUTENCAO", False)
    return TestClient(server.app)


# ── boot em produção ─────────────────────────────────────────────────────────────────────────────

def test_producao_completa_passa():
    assert server._validar_config_producao(dict(_PROD_OK)) == []


@pytest.mark.parametrize("ajuste", [
    {"JFN_DASH_PASSWORD": ""},                   # sem senha
    {"JFN_DASH_PASSWORD": "curta-demais"},       # senha < 20
    {"JFN_DASH_SECRET": ""},                     # sem secret
    {"JFN_DASH_SECRET": "x" * 31},               # secret < 32
    {"JFN_DASH_SECRET": "s" * 40, "JFN_DASH_PASSWORD": "s" * 40},  # secret == senha
    {"COOKIE_SECURE": ""},                       # sem Secure
    {"COOKIE_SECURE": "0"},
])
def test_producao_incompleta_falha(ajuste):
    env = {**_PROD_OK, **ajuste}
    probs = server._validar_config_producao(env)
    assert probs, ajuste
    # a mensagem nunca carrega o VALOR do segredo
    assert not any(v and len(v) >= 8 and v in " ".join(probs) for v in env.values() if v != "producao")


def test_jfn_env_invalido_falha():
    assert server._validar_config_producao({**_PROD_OK, "JFN_ENV": "prod"})


def test_fora_de_producao_nao_exige():
    assert server._validar_config_producao({"JFN_ENV": "local"}) == []
    assert server._validar_config_producao({"JFN_ENV": "teste"}) == []


def _main(monkeypatch, env, *args):
    for k in ("JFN_ENV", "JFN_DASH_PASSWORD", "JFN_DASH_SECRET", "COOKIE_SECURE"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    subiu = []
    monkeypatch.setattr(server.uvicorn, "run", lambda *a, **kw: subiu.append(kw))
    monkeypatch.setattr(sys, "argv", ["server.py", *args])
    try:
        server.main()
    except SystemExit as e:
        return e.code, subiu
    return None, subiu


def test_boot_producao_sem_senha_aborta_sem_subir(monkeypatch):
    code, subiu = _main(monkeypatch, {"JFN_ENV": "producao", "COOKIE_SECURE": "1", "JFN_DASH_SECRET": _SECRET})
    assert code == 1 and subiu == []


def test_boot_producao_senha_curta_aborta(monkeypatch):
    code, subiu = _main(monkeypatch, {**_PROD_OK, "JFN_DASH_PASSWORD": "abc"})
    assert code == 1 and subiu == []


def test_boot_producao_sem_cookie_secure_aborta(monkeypatch):
    env = dict(_PROD_OK)
    env.pop("COOKIE_SECURE")
    code, subiu = _main(monkeypatch, env)
    assert code == 1 and subiu == []


def test_checar_config_sai_0_ou_1_sem_subir(monkeypatch):
    code, subiu = _main(monkeypatch, _PROD_OK, "--checar-config")
    assert code == 0 and subiu == []
    code, subiu = _main(monkeypatch, {**_PROD_OK, "COOKIE_SECURE": ""}, "--checar-config")
    assert code == 1 and subiu == []


def test_host_vem_de_jfn_host_default_loopback(monkeypatch):
    monkeypatch.delenv("JFN_HOST", raising=False)
    monkeypatch.setattr(sys, "argv", ["server.py"])
    assert server.parse_args().host == "127.0.0.1"
    monkeypatch.setenv("JFN_HOST", "::1")
    assert server.parse_args().host == "::1"


# ── quem é localhost ─────────────────────────────────────────────────────────────────────────────

def test_locais_so_loopback_e_testclient_so_em_teste():
    assert server._hosts_locais("producao") == {"127.0.0.1", "::1"}
    assert server._hosts_locais("local") == {"127.0.0.1", "::1"}
    assert server._hosts_locais("teste") == {"127.0.0.1", "::1", "testclient"}


def test_local_com_x_forwarded_for_exige_login(cli):
    for h in ({"X-Forwarded-For": "127.0.0.1"}, {"X-Real-Ip": "127.0.0.1"}, {"Forwarded": "for=127.0.0.1"}):
        assert cli.get("/status", headers=h, follow_redirects=False).status_code == 303, h
        assert cli.get("/api/casos", headers=h).status_code == 401, h


def test_sem_senha_o_gate_nao_desliga(monkeypatch, tmp_path):
    """O ramo `if not _DASH_SENHA: return await call_next(request)` saiu: sem senha, ninguém de fora entra."""
    monkeypatch.setattr(server, "_DASH_SENHA", "")
    monkeypatch.setattr(server, "_MANUTENCAO", False)
    c = TestClient(server.app)
    assert c.get("/api/casos", headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 401
    # e login com senha vazia não abre sessão
    monkeypatch.setattr(server, "_RATELIMIT_DB", tmp_path / "rl.db")
    r = c.post("/login_jfn", data={"senha": ""}, follow_redirects=False)
    assert r.headers.get("location") != "/painel"


def _asgi_get(path, client):
    """Chamada ASGI crua — o TestClient não deixa `client=None`."""
    enviado = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        enviado.append(msg)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
             "root_path": "", "headers": [(b"host", b"x")], "client": client, "server": ("x", 80)}
    asyncio.run(server.app(scope, receive, send))
    return next(m["status"] for m in enviado if m["type"] == "http.response.start")


def test_client_none_nao_e_localhost(cli):
    assert _asgi_get("/api/casos", None) == 401
    assert _asgi_get("/status", None) == 303


# ── token e epoch ────────────────────────────────────────────────────────────────────────────────

def test_token_valido_e_epoch_trocado_invalida(monkeypatch):
    monkeypatch.setattr(server, "_DASH_EPOCH", "1")
    tok = server._dash_token()
    assert server._dash_token_ok(tok)
    monkeypatch.setattr(server, "_DASH_EPOCH", "2")
    assert not server._dash_token_ok(tok)
    assert server._dash_token_ok(server._dash_token())


def test_token_sem_epoch_formato_antigo_invalido(monkeypatch):
    import hashlib
    import hmac
    import time
    exp = str(int(time.time()) + 3600)
    antigo = f"{exp}." + hmac.new(server._DASH_SECRET, exp.encode(), hashlib.sha256).hexdigest()
    assert not server._dash_token_ok(antigo)


def test_ttl_padrao_7_dias():
    assert server._DASH_TTL_PADRAO == 7 * 24 * 3600


def test_cookie_httponly_samesite_secure(cli, monkeypatch):
    monkeypatch.setattr(server, "_DASH_COOKIE_SECURE", True)
    r = cli.post("/login_jfn", data={"senha": "senha-de-teste"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/painel"
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=lax" in sc and "secure" in sc
    assert f"max-age={server._DASH_TTL}" in sc


# ── rate limit persistente ───────────────────────────────────────────────────────────────────────

def test_rate_limit_persiste_no_sqlite(cli):
    for _ in range(5):
        assert cli.post("/login_jfn", data={"senha": "errada"}, follow_redirects=False).status_code == 303
    assert server._RATELIMIT_DB.exists()
    # "restart": nada em memória — a contagem vem do banco
    c2 = TestClient(server.app)
    assert c2.post("/login_jfn", data={"senha": "senha-de-teste"}, follow_redirects=False).status_code == 429


# ── manutenção ───────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def manut(cli, monkeypatch):
    monkeypatch.setattr(server, "_MANUTENCAO", True)
    monkeypatch.setattr(server, "_MANUTENCAO_DESDE", "2026-11-24 12:25")
    return cli


def test_manutencao_get_passa(manut):
    assert manut.get("/status").status_code == 200


@pytest.mark.parametrize("metodo", ["POST", "PUT", "PATCH", "DELETE"])
def test_manutencao_escrita_503(manut, metodo):
    r = manut.request(metodo, "/api/qualquer-coisa", json={})
    assert r.status_code == 503
    corpo = r.json()
    assert corpo["manutencao"] is True and corpo["desde"] == "2026-11-24 12:25"


def test_manutencao_login_e_logout_continuam(manut):
    r = manut.post("/login_jfn", data={"senha": "senha-de-teste"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/painel"
    assert manut.get("/logout_jfn", follow_redirects=False).status_code == 303


@pytest.mark.parametrize("rota", ["/ws", "/tunnel"])
def test_manutencao_fecha_websocket_ate_para_o_local_logado(manut, rota):
    """25/11/2026 (O0.3): /ws aciona o agente e /tunnel grava OB — em manutenção nenhum dos dois abre, nem com
    sessão válida (o middleware HTTP não roda em WebSocket; a régua é `_ws_autorizado`)."""
    from starlette.websockets import WebSocketDisconnect
    manut.post("/login_jfn", data={"senha": "senha-de-teste"}, follow_redirects=False)
    with pytest.raises(WebSocketDisconnect) as e:
        with manut.websocket_connect(rota) as w:
            w.send_text('{"type": "chat", "content": "x"}')
            w.receive_text()
    assert e.value.code == 1008


def test_manutencao_html_leva_faixa(manut):
    r = manut.get("/login_jfn")
    assert r.status_code == 200
    assert "Em manutenção — dados congelados em 2026-11-24 12:25" in r.text
    assert r.text.count('id="jfn-manutencao"') == 1


def test_manutencao_json_nao_ganha_faixa(manut):
    r = manut.get("/status")
    json.loads(r.text)  # continua JSON válido
    assert "jfn-manutencao" not in r.text


def test_sem_manutencao_post_nao_e_503(cli):
    assert cli.post("/api/qualquer-coisa", json={}).status_code != 503
    assert "jfn-manutencao" not in cli.get("/login_jfn").text


# ── WebSocket: middleware HTTP não cobre — régua própria (24/11, medido aberto pelo Funnel) ──────

from starlette.websockets import WebSocketDisconnect  # noqa: E402

_PROXY = {"x-forwarded-for": "203.0.113.7"}


@pytest.mark.parametrize("rota", ["/ws", "/tunnel"])
def test_websocket_sem_login_via_proxy_recusa(cli, rota):
    with pytest.raises(WebSocketDisconnect) as e:
        with cli.websocket_connect(rota, headers=_PROXY) as ws:
            ws.receive_text()
    assert e.value.code == 1008


@pytest.mark.parametrize("rota", ["/ws", "/tunnel"])
def test_websocket_fechado_em_manutencao_mesmo_local(manut, rota):
    with pytest.raises(WebSocketDisconnect) as e:
        with manut.websocket_connect(rota) as ws:
            ws.receive_text()
    assert e.value.code == 1008


def test_ws_autorizado_aceita_cookie_valido(monkeypatch):
    monkeypatch.setattr(server, "_MANUTENCAO", False)

    class _WS:
        client = None
        headers = _PROXY
        cookies = {server._DASH_COOKIE: server._dash_token()}

    assert server._ws_autorizado(_WS())
    _WS.cookies = {}
    assert not server._ws_autorizado(_WS())
