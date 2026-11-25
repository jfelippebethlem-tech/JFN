"""Cliente HTTP seguro ÚNICO para URL que vem de dado externo (anti-SSRF) — plano mestre O0.4, §3.11.

Uso obrigatório sempre que a URL não for constante do código: link raspado de página, campo `url`
de JSON de API (PNCP, CKAN), domínio tirado de cadastro, URL guardada em banco que veio de fora.

O que ele garante, por salto:
  1. esquema http/https, sem credencial embutida (`user@host`), porta 80/443;
  2. host dentro da allowlist da POLÍTICA do uso (host exato ou subdomínio); política sem
     allowlist (`dominios=None`) aceita qualquer host, mas continua barrando IP interno;
  3. o nome é resolvido UMA vez; se QUALQUER endereço cair em faixa interna (metadata
     169.254.0.0/16, 127/8, ::1, RFC1918, CGNAT 100.64/10, link-local e ULA IPv6, …), bloqueia;
  4. a conexão vai para o IP validado (FIXADO) — o urllib3 não volta ao DNS, então DNS
     rebinding não tem segunda resolução para explorar; o SNI e a verificação do certificado
     continuam sendo feitos contra o NOME;
  5. redirect é seguido À MÃO, no máximo `max_saltos`, e cada `Location` passa de novo por 1–4;
     https → http é recusado.

CGNAT (100.64/10 — a faixa do Tailscale) só passa para os IPs listados em `alvos_internos`.
Proxy do ambiente (HTTP(S)_PROXY) é ignorado de propósito: proxy desfaria a fixação do IP.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
from requests.cookies import extract_cookies_to_jar
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError
from urllib3.util import connection as _u3conn


class RedeBloqueada(ValueError):
    """A URL (ou um salto de redirect) viola a política de saída de rede."""


# Faixas barradas mesmo quando `ipaddress` as considera globais (e as óbvias, explícitas para leitura).
_FAIXAS_BLOQUEADAS = tuple(ipaddress.ip_network(f) for f in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
    "172.16.0.0/12", "192.0.0.0/24", "192.168.0.0/16", "198.18.0.0/15", "224.0.0.0/4",
    "240.0.0.0/4", "255.255.255.255/32",
    "::/128", "::1/128", "fe80::/10", "fc00::/7", "ff00::/8",
    "64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32",  # NAT64/6to4/Teredo embutem IPv4
))
_STATUS_REDIRECT = {301, 302, 303, 307, 308}
_PORTAS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class Politica:
    """Allowlist de saída de um USO. `dominios=None` = qualquer host público (ex.: site de empresa)."""
    uso: str
    dominios: Optional[frozenset[str]]
    alvos_internos: frozenset[str] = frozenset()
    max_saltos: int = 3


def _p(uso: str, *dominios: str) -> Politica:
    return Politica(uso, frozenset(dominios))


POLITICAS: dict[str, Politica] = {
    "sei": _p("sei", "sei.rj.gov.br", "prefeitura.sei.rio"),
    "pncp": _p("pncp", "pncp.gov.br"),
    "ckan_rj": _p("ckan_rj", "rj.gov.br"),
    "governo_rj": _p("governo_rj", "rj.gov.br"),
    "contasrio": _p("contasrio", "contasrio.rio.rj.gov.br", "rio.rj.gov.br", "prefeitura.rio"),
    "camara": _p("camara", "dadosabertos.camara.leg.br", "camara.leg.br"),
    "web_aberta": Politica("web_aberta", None),
}


def politica(uso: str) -> Politica:
    try:
        return POLITICAS[uso]
    except KeyError as e:
        raise RedeBloqueada(f"uso de rede sem política declarada: {uso!r}") from e


def ip_bloqueado(ip: str, pol: Politica) -> bool:
    """True se o IP é interno/reservado e não é alvo interno explícito da política."""
    end = ipaddress.ip_address(ip.split("%", 1)[0])
    if str(end) in pol.alvos_internos:
        return False
    if end.version == 6 and end.ipv4_mapped is not None:
        return ip_bloqueado(str(end.ipv4_mapped), pol)
    if any(end in f for f in _FAIXAS_BLOQUEADAS if f.version == end.version):
        return True
    return not end.is_global


def _host_permitido(host: str, pol: Politica) -> bool:
    if pol.dominios is None:
        return True
    return any(host == d or host.endswith("." + d) for d in pol.dominios)


@dataclass(frozen=True)
class Alvo:
    esquema: str
    host: str
    porta: int
    ip: str


def _resolver(host: str, porta: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, porta, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise RedeBloqueada(f"host não resolve: {host}") from e
    return [str(i[4][0]) for i in infos]


def exigir_host(url: str, uso: str) -> str:
    """Só esquema + allowlist de host, SEM resolver DNS — para quem segue link de paginação com
    um cliente de host fixo que não segue redirect (o socket só abre num host da allowlist)."""
    pol = politica(uso)
    p = urlsplit(url)
    host = (p.hostname or "").rstrip(".").lower()
    if (p.scheme or "").lower() not in _PORTAS or not host or p.username is not None:
        raise RedeBloqueada(f"URL recusada: {url!r}")
    if not _host_permitido(host, pol):
        raise RedeBloqueada(f"host {host!r} fora da allowlist do uso {pol.uso!r}")
    return url


def validar_url(url: str, pol: Politica) -> Alvo:
    """Valida esquema/host/porta contra a política e devolve o alvo com o IP já fixado."""
    p = urlsplit(url)
    esquema = (p.scheme or "").lower()
    if esquema not in _PORTAS:
        raise RedeBloqueada(f"esquema de URL não permitido: {esquema!r}")
    if p.username is not None or p.password is not None:
        raise RedeBloqueada("URL com credencial embutida (user@host) — recusada")
    host = (p.hostname or "").rstrip(".").lower()
    if not host:
        raise RedeBloqueada("URL sem host")
    try:
        porta = p.port or _PORTAS[esquema]
    except ValueError as e:
        raise RedeBloqueada(f"porta inválida em {url!r}") from e
    if porta != _PORTAS[esquema]:
        raise RedeBloqueada(f"porta {porta} fora do padrão de {esquema}")
    if not _host_permitido(host, pol):
        raise RedeBloqueada(f"host {host!r} fora da allowlist do uso {pol.uso!r}")
    ips = _resolver(host, porta)
    if not ips:
        raise RedeBloqueada(f"host sem endereço: {host}")
    barrados = [ip for ip in ips if ip_bloqueado(ip, pol)]
    if barrados:
        raise RedeBloqueada(f"host {host!r} resolve para IP interno {barrados[0]} — bloqueado (SSRF)")
    return Alvo(esquema, host, porta, ips[0])


def _criar_conexao(endereco, timeout, source_address=None, socket_options=None):
    """Ponto único de abertura de socket (os testes trocam por um registrador)."""
    return _u3conn.create_connection(endereco, timeout, source_address=source_address,
                                     socket_options=socket_options)


def _classes_fixadas(ip: str, pol: Politica):
    """Pools do urllib3 cuja conexão abre o socket no IP fixado, mantendo host/SNI pelo nome."""
    def _new_conn(self):
        if ip_bloqueado(ip, pol):  # revalida no ato de conectar (defesa em profundidade)
            raise RedeBloqueada(f"conexão a IP interno {ip} recusada")
        try:
            return _criar_conexao((ip, self.port), self.timeout, self.source_address,
                                  self.socket_options)
        except OSError as e:
            raise NewConnectionError(self, f"Failed to establish a new connection: {e}") from e

    conn_http = type("_ConexaoFixadaHTTP", (HTTPConnection,), {"_new_conn": _new_conn})
    conn_https = type("_ConexaoFixadaHTTPS", (HTTPSConnection,), {"_new_conn": _new_conn})
    pool_http = type("_PoolFixadoHTTP", (HTTPConnectionPool,), {"ConnectionCls": conn_http})
    pool_https = type("_PoolFixadoHTTPS", (HTTPSConnectionPool,), {"ConnectionCls": conn_https})
    return {"http": pool_http, "https": pool_https}


class _AdaptadorFixado(HTTPAdapter):
    def __init__(self, ip: str, pol: Politica):
        self._ip, self._pol = ip, pol
        super().__init__(max_retries=0)

    def init_poolmanager(self, *a, **kw):
        super().init_poolmanager(*a, **kw)
        self.poolmanager.pool_classes_by_scheme = _classes_fixadas(self._ip, self._pol)


def _ler_limitado(resp: requests.Response, max_bytes: int) -> bytes:
    partes, total = [], 0
    for ch in resp.iter_content(65536):
        total += len(ch)
        if total > max_bytes:
            resp.close()
            raise RedeBloqueada(f"resposta excede {max_bytes} bytes")
        partes.append(ch)
    return b"".join(partes)


def _abrir(url: str, pol: Politica, *, sessao: Optional[requests.Session], timeout,
           headers: Optional[dict], params: Optional[dict], verify) -> requests.Response:
    """GET com redirect manual. Devolve a resposta final ABERTA (stream) — quem chama lê e fecha."""
    sess = sessao if sessao is not None else requests.Session()
    atual, anterior = url, None
    for salto in range(pol.max_saltos + 1):
        alvo = validar_url(atual, pol)
        if anterior == "https" and alvo.esquema == "http":
            raise RedeBloqueada("redirect https → http recusado")
        prep = sess.prepare_request(requests.Request(
            "GET", atual, headers=headers, params=params if salto == 0 else None))
        adaptador = _AdaptadorFixado(alvo.ip, pol)
        try:
            resp = adaptador.send(prep, stream=True, timeout=timeout, verify=verify, proxies={})
        finally:
            adaptador.close()
        extract_cookies_to_jar(sess.cookies, prep, resp.raw)
        if resp.status_code not in _STATUS_REDIRECT or "location" not in resp.headers:
            return resp
        destino = urljoin(resp.url or atual, resp.headers["location"])
        resp.close()
        anterior, atual = alvo.esquema, destino
    raise RedeBloqueada(f"mais de {pol.max_saltos} redirects a partir de {url!r}")


def obter(url: str, uso: str | Politica, *, sessao: Optional[requests.Session] = None,
          timeout=30, headers: Optional[dict] = None, params: Optional[dict] = None,
          verify=True, max_bytes: int = 200 * 1024 * 1024) -> requests.Response:
    """GET seguro; devolve `requests.Response` com o corpo já lido (`.content`, `.text`,
    `.json()`, `.status_code`, `.raise_for_status()`). Corpo acima de `max_bytes` → RedeBloqueada."""
    pol = uso if isinstance(uso, Politica) else politica(uso)
    resp = _abrir(url, pol, sessao=sessao, timeout=timeout, headers=headers, params=params,
                  verify=verify)
    try:
        resp._content = _ler_limitado(resp, max_bytes)
    finally:
        resp.close()
    return resp


def obter_para_arquivo(url: str, uso: str | Politica, destino: Path, *,
                       sessao: Optional[requests.Session] = None, timeout=120,
                       headers: Optional[dict] = None, verify=True,
                       max_bytes: int = 4 * 1024 ** 3) -> requests.Response:
    """GET seguro gravando o corpo em `destino` aos pedaços (arquivo grande). Levanta
    `requests.HTTPError` em status ≥ 400 antes de gravar qualquer byte."""
    pol = uso if isinstance(uso, Politica) else politica(uso)
    resp = _abrir(url, pol, sessao=sessao, timeout=timeout, headers=headers, params=None,
                  verify=verify)
    try:
        resp.raise_for_status()
        total = 0
        with open(destino, "wb") as f:
            for ch in resp.iter_content(1 << 20):
                total += len(ch)
                if total > max_bytes:
                    raise RedeBloqueada(f"resposta excede {max_bytes} bytes")
                f.write(ch)
    finally:
        resp.close()
    return resp


async def obter_async(url: str, uso: str | Politica, **kw) -> requests.Response:
    """`obter` para código async (roda em thread; não bloqueia o loop)."""
    return await asyncio.to_thread(obter, url, uso, **kw)


def hosts_da_politica(uso: str) -> Iterable[str]:
    pol = politica(uso)
    return sorted(pol.dominios or ())
