"""Cliente HTTP seguro (O0.4): redirect manual validado, IP fixado (sem rebinding), allowlist.

Sem rede externa: o DNS é trocado por um mapa e o socket é desviado para um servidor HTTP
local — o teste registra para ONDE o cliente tentou conectar, que é o que importa no SSRF."""
from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests

from compliance_agent.adaptadores import rede_segura as rs

IP_PUBLICO = "200.144.0.10"      # endereço global fictício que o "DNS" do teste devolve


class _Handler(BaseHTTPRequestHandler):
    rotas: dict = {}

    def do_GET(self):  # noqa: N802 — API do http.server
        status, cab, corpo = self.rotas.get(self.path, (404, {}, b"nao achou"))
        if callable(corpo):
            corpo = corpo(self)
        self.send_response(status)
        for k, v in cab.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *a):
        return


@pytest.fixture()
def rede(monkeypatch):
    """Servidor local + DNS falso + registro das conexões abertas pelo cliente."""
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    porta = srv.server_address[1]
    estado = {"conexoes": [], "dns": {}, "consultas": []}

    def _resolver(host, p):
        estado["consultas"].append(host)
        r = estado["dns"].get(host)
        if callable(r):
            r = r()
        if r is None:
            raise rs.RedeBloqueada(f"host não resolve: {host}")
        return list(r)

    def _conectar(endereco, timeout, source_address=None, socket_options=None):
        estado["conexoes"].append(endereco)
        return socket.create_connection(("127.0.0.1", porta), timeout)

    monkeypatch.setattr(rs, "_resolver", _resolver)
    monkeypatch.setattr(rs, "_criar_conexao", _conectar)
    _Handler.rotas = {}
    yield estado
    srv.shutdown()
    srv.server_close()


# ── classificação de IP ───────────────────────────────────────────────────────

@pytest.mark.parametrize("ip", [
    "169.254.169.254", "169.254.0.2", "127.0.0.1", "127.0.0.53", "::1", "0.0.0.0",
    "10.0.0.208", "172.16.5.4", "192.168.0.1", "100.74.228.51", "100.100.100.100",
    "fe80::1", "fd7a:115c:a1e0::53", "::ffff:169.254.169.254", "::ffff:127.0.0.1",
    "64:ff9b::a9fe:a9fe", "224.0.0.1",
])
def test_ip_interno_bloqueado(ip):
    assert rs.ip_bloqueado(ip, rs.politica("sei"))


@pytest.mark.parametrize("ip", ["8.8.8.8", "200.144.0.10", "2606:4700:4700::1111"])
def test_ip_publico_passa(ip):
    assert not rs.ip_bloqueado(ip, rs.politica("sei"))


def test_cgnat_so_passa_o_alvo_tailscale_explicito():
    pol = rs.Politica("pg_vm2", frozenset({"vm2"}), alvos_internos=frozenset({"100.74.228.51"}))
    assert not rs.ip_bloqueado("100.74.228.51", pol)
    assert rs.ip_bloqueado("100.74.228.52", pol)
    assert rs.ip_bloqueado("169.254.169.254", pol)


# ── allowlist ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://evil.example/captcha.php",
    "https://sei.rj.gov.br.evil.example/x",       # sufixo enganoso
    "https://xsei.rj.gov.br/x",                    # não é subdomínio
    "https://user@sei.rj.gov.br/x",                # credencial embutida
    "https://sei.rj.gov.br:8443/x",                # porta fora do padrão
    "file:///etc/passwd", "gopher://sei.rj.gov.br/", "data:image/png;base64,AAAA",
    "http://169.254.169.254/latest/meta-data/",
])
def test_allowlist_recusa(rede, url):
    rede["dns"]["sei.rj.gov.br"] = [IP_PUBLICO]
    with pytest.raises(rs.RedeBloqueada):
        rs.validar_url(url, rs.politica("sei"))
    assert rede["conexoes"] == []


def test_allowlist_aceita_host_e_subdominio(rede):
    rede["dns"].update({"prefeitura.sei.rio": [IP_PUBLICO], "www.sei.rj.gov.br": [IP_PUBLICO]})
    assert rs.validar_url("https://prefeitura.sei.rio/x", rs.politica("sei")).ip == IP_PUBLICO
    assert rs.validar_url("http://WWW.sei.rj.gov.br./x", rs.politica("sei")).host == "www.sei.rj.gov.br"


def test_uso_sem_politica_e_recusado():
    with pytest.raises(rs.RedeBloqueada):
        rs.politica("inexistente")


def test_exigir_host_paginacao():
    assert rs.exigir_host("https://dadosabertos.camara.leg.br/api/v2/x?pagina=2", "camara")
    with pytest.raises(rs.RedeBloqueada):
        rs.exigir_host("http://169.254.169.254/api/v2/x", "camara")


# ── redirect manual ───────────────────────────────────────────────────────────

def test_302_para_metadata_e_bloqueado_sem_conectar(rede):
    rede["dns"]["sei.rj.gov.br"] = [IP_PUBLICO]
    _Handler.rotas["/captcha.php"] = (302, {"Location": "http://169.254.169.254/latest/meta-data/"}, b"")
    with pytest.raises(rs.RedeBloqueada, match="169.254.169.254"):
        rs.obter("http://sei.rj.gov.br/captcha.php", "sei")
    assert rede["conexoes"] == [(IP_PUBLICO, 80)]          # nunca abriu socket para a metadata


def test_302_para_host_da_allowlist_que_resolve_para_metadata(rede):
    rede["dns"].update({"sei.rj.gov.br": [IP_PUBLICO], "meta.sei.rj.gov.br": ["169.254.169.254"]})
    _Handler.rotas["/a"] = (302, {"Location": "http://meta.sei.rj.gov.br/b"}, b"")
    with pytest.raises(rs.RedeBloqueada, match="IP interno"):
        rs.obter("http://sei.rj.gov.br/a", "sei")
    assert rede["conexoes"] == [(IP_PUBLICO, 80)]


def test_302_para_fora_da_allowlist(rede):
    rede["dns"].update({"sei.rj.gov.br": [IP_PUBLICO], "evil.example": [IP_PUBLICO]})
    _Handler.rotas["/a"] = (302, {"Location": "http://evil.example/b"}, b"")
    with pytest.raises(rs.RedeBloqueada, match="allowlist"):
        rs.obter("http://sei.rj.gov.br/a", "sei")


def test_redirect_valido_segue_e_preserva_cookie(rede):
    rede["dns"]["sei.rj.gov.br"] = [IP_PUBLICO]
    _Handler.rotas["/a"] = (302, {"Location": "/b", "Set-Cookie": "PHPSESSID=abc; Path=/"}, b"")
    _Handler.rotas["/b"] = (200, {}, lambda h: b"cookie=" + (h.headers.get("Cookie") or "").encode())
    sess = requests.Session()
    r = rs.obter("http://sei.rj.gov.br/a", "sei", sessao=sess)
    assert r.status_code == 200 and r.content == b"cookie=PHPSESSID=abc"
    assert sess.cookies.get("PHPSESSID") == "abc"          # jar do chamador atualizado


def test_mais_de_tres_saltos_recusado(rede):
    rede["dns"]["sei.rj.gov.br"] = [IP_PUBLICO]
    for i in range(5):
        _Handler.rotas[f"/r{i}"] = (302, {"Location": f"/r{i + 1}"}, b"")
    with pytest.raises(rs.RedeBloqueada, match="redirects"):
        rs.obter("http://sei.rj.gov.br/r0", "sei")
    assert len(rede["conexoes"]) <= 4


def test_corpo_acima_do_teto(rede):
    rede["dns"]["sei.rj.gov.br"] = [IP_PUBLICO]
    _Handler.rotas["/g"] = (200, {}, b"x" * 5000)
    with pytest.raises(rs.RedeBloqueada, match="excede"):
        rs.obter("http://sei.rj.gov.br/g", "sei", max_bytes=1000)


# ── DNS rebinding ─────────────────────────────────────────────────────────────

def test_rebinding_conecta_no_ip_validado(rede):
    respostas = iter([[IP_PUBLICO], ["127.0.0.1"], ["169.254.169.254"]])
    rede["dns"]["sei.rj.gov.br"] = lambda: next(respostas)
    _Handler.rotas["/x"] = (200, {}, b"ok")
    r = rs.obter("http://sei.rj.gov.br/x", "sei")
    assert r.content == b"ok"
    assert rede["consultas"] == ["sei.rj.gov.br"]           # uma resolução só
    assert rede["conexoes"] == [(IP_PUBLICO, 80)]          # socket no IP que foi validado


def test_resposta_dns_mista_e_bloqueada(rede):
    rede["dns"]["sei.rj.gov.br"] = [IP_PUBLICO, "127.0.0.1"]
    with pytest.raises(rs.RedeBloqueada):
        rs.obter("http://sei.rj.gov.br/x", "sei")
    assert rede["conexoes"] == []


def test_conexao_revalida_ip_no_ato(monkeypatch):
    """Defesa em profundidade: mesmo que alguém fixe um IP interno, o socket não abre."""
    chamadas = []
    monkeypatch.setattr(rs, "_criar_conexao", lambda *a, **k: chamadas.append(a))
    pools = rs._classes_fixadas("169.254.169.254", rs.politica("sei"))
    conn = pools["http"].ConnectionCls("sei.rj.gov.br", 80)
    with pytest.raises(rs.RedeBloqueada):
        conn._new_conn()
    assert chamadas == []


# ── o ponto migrado: captcha_solver ───────────────────────────────────────────

def test_captcha_download_302_para_metadata_bloqueado(rede):
    from compliance_agent import captcha_solver
    rede["dns"]["sei.rj.gov.br"] = [IP_PUBLICO]
    _Handler.rotas["/sei/captcha.php"] = (302, {"Location": "http://169.254.169.254/opc/v2/instance/"}, b"")
    with pytest.raises(rs.RedeBloqueada):
        captcha_solver._download("http://sei.rj.gov.br/sei/captcha.php")
    assert rede["conexoes"] == [(IP_PUBLICO, 80)]


def test_captcha_download_normal(rede):
    from compliance_agent import captcha_solver
    rede["dns"]["prefeitura.sei.rio"] = [IP_PUBLICO]
    _Handler.rotas["/c.png"] = (200, {"Content-Type": "image/png"}, b"\x89PNG-fake")
    assert captcha_solver._download("http://prefeitura.sei.rio/c.png") == b"\x89PNG-fake"
