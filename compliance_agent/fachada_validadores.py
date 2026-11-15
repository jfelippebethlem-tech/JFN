# -*- coding: utf-8 -*-
"""Validadores INDEPENDENTES de sede real e a combinação deles (pedido do dono, 14/11/2026).

"Busque site das empresas, redes sociais e mais validadores." Tudo grátis e sem chave paga:

  * SITE da empresa — a partir do domínio do e-mail que a própria Receita registra. Confere se a página
    cita o CNPJ, a razão social e o logradouro; colhe os links de Instagram/Facebook/LinkedIn que o
    próprio site publica. Medido na base (14.349 credores PJ do SIAFE): 6.111 (42,6%) têm domínio próprio;
    4.738 usam webmail e 3.500 não têm e-mail — para esses o validador é INDISPONÍVEL, nunca "suspeito".
  * REDES SOCIAIS — só as que o site da empresa aponta. Busca aberta (motor de busca / Instagram /
    Facebook / LinkedIn) não é confiável sem chave: o DuckDuckGo HTML respondeu 202 (desafio anti-robô) da
    VM, e as redes exigem login para busca. Declarado como limite, não fingido.
  * CEP × logradouro (ViaCEP), telefone/e-mail repetidos e sala compartilhada (base da Receita) — já
    existiam em `geo.sede_real`; aqui só entram na soma.
  * OSM (Nominatim/Overpass) — o Overpass público não respondeu da VM em 14/11/2026 (timeout/406/504 em 3
    espelhos; 0 de 51 pontos apuráveis). Entra quando houver; ausente = INDISPONÍVEL.

REGRA DA COMBINAÇÃO: nenhum validador condena sozinho. 🔴 exige ≥ 2 fontes independentes e saldo ≥ 6;
substância (site que cita o CNPJ, foto do lote edificada, rede de filiais) pesa CONTRA a suspeita.
Indício ≠ acusação; INDISPONÍVEL ≠ 0.
"""
from __future__ import annotations

import sqlite3

import logging
import re
import threading
import time
import unicodedata

logger = logging.getLogger(__name__)

_WEBMAIL = {"gmail.com", "gmail.com.br", "hotmail.com", "hotmail.com.br", "yahoo.com", "yahoo.com.br",
            "outlook.com", "outlook.com.br", "live.com", "msn.com", "bol.com.br", "uol.com.br", "terra.com.br",
            "ig.com.br", "globo.com", "icloud.com", "oi.com.br", "r7.com", "zipmail.com.br", "ymail.com",
            "rocketmail.com", "superig.com.br", "aol.com", "veloxmail.com.br", "globomail.com", "zoho.com",
            "protonmail.com", "proton.me", "yandex.com"}
# Domínio usado por muitas empresas sem relação entre si é do escritório (Contabilizei abre CNPJ para
# milhares), não da empresa. Mesma faixa "rara" de geo.sede_real (_RARO_MAX = 20 para identidade); aqui o
# corte é mais duro porque o site precisa ser DA empresa.
_DOMINIO_MAX_EMPRESAS = 2


def dominio_corporativo(email, n_empresas_no_dominio: int = 1) -> str | None:
    """Domínio próprio da empresa a partir do e-mail da Receita, ou None (webmail, governo, escritório)."""
    e = str(email or "").strip().lower()
    if "@" not in e:
        return None
    d = e.rsplit("@", 1)[1].strip(" .;,")
    if not d or "." not in d or d in _WEBMAIL or d.endswith(".gov.br") or d.endswith(".gov"):
        return None
    if n_empresas_no_dominio > _DOMINIO_MAX_EMPRESAS:
        return None
    return d


def _norm(s) -> str:
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", t)


_GENERICOS_RAZAO = {"ltda", "eireli", "me", "epp", "sa", "s", "a", "cia", "comercio", "servicos", "servico",
                    "industria", "e", "de", "da", "do", "das", "dos", "para", "em", "empresa", "limitada",
                    "unipessoal", "brasil", "rio", "janeiro"}
_REDES = {"instagram": r"instagram\.com/[A-Za-z0-9_.]+", "facebook": r"facebook\.com/[A-Za-z0-9_.\-]+",
          "linkedin": r"linkedin\.com/(?:company|in)/[A-Za-z0-9_\-]+"}


def _tokens(s, descartar=_GENERICOS_RAZAO) -> set[str]:
    return {t for t in re.sub(r"[^a-z0-9]+", " ", _norm(s)).split() if len(t) > 2 and t not in descartar}


def analisar_pagina(html: str, *, cnpj: str, razao: str, logradouro: str) -> dict:
    """Puro: a página cita o CNPJ? a razão social? o logradouro? Quais redes sociais ela aponta?"""
    texto = re.sub(r"<[^>]+>", " ", html or "")
    digitos = re.sub(r"\D", "", texto)
    c = re.sub(r"\D", "", str(cnpj or ""))
    cita_cnpj = bool(c) and (c in digitos or c[:8] in re.sub(r"\D", "", " ".join(
        re.findall(r"\d{2}\.?\d{3}\.?\d{3}", texto))))
    pagina = _tokens(texto, descartar=set())
    rz = _tokens(razao)
    cita_razao = bool(rz) and len(rz & pagina) / len(rz) >= 0.6
    from compliance_agent.geo.sede_real import _tokens_logradouro
    lg = _tokens_logradouro(logradouro)
    cita_end = bool(lg) and len(lg & pagina) / len(lg) >= 0.6
    redes = sorted({nome for nome, rx in _REDES.items() if re.search(rx, html or "", re.I)})
    return {"cita_cnpj": cita_cnpj, "cita_razao": cita_razao, "cita_endereco": cita_end, "redes": redes}


_ult = [0.0]
_lock = threading.Lock()


def _fetch_padrao(url: str) -> tuple[int | None, str]:
    """GET educado (1 req/s, 12 s, até 1,5 MB). Erro de rede → (None, '')."""
    import httpx
    with _lock:
        espera = 1.0 - (time.monotonic() - _ult[0])
        if espera > 0:
            time.sleep(espera)
        _ult[0] = time.monotonic()
    try:
        with httpx.Client(follow_redirects=True, timeout=12,
                          headers={"User-Agent": "JFN-fiscalizacao/1.0 (gabinete RJ)"}) as cli:
            r = cli.get(url)
            return r.status_code, r.text[:1_500_000]
    except (httpx.HTTPError, ValueError, UnicodeDecodeError) as exc:
        logger.debug("site indisponível %s: %s", url, exc)
        return None, ""


def checar_site(dominio: str, cnpj: str, razao: str, logradouro: str, *, fetch=None,
                usar_cache: bool = True) -> dict:
    """Visita o site do domínio e classifica: cita_cnpj | cita_nome_ou_endereco | sem_mencao | fora_do_ar.
    Cache de 30 dias (só resposta real; falha de rede não é cacheada)."""
    cache = k = None
    if usar_cache:
        try:
            from compliance_agent.providers.base import CacheSQLite
            cache = CacheSQLite()
            k = cache.chave("site:empresa", {"d": dominio, "c": cnpj})
            hit = cache.get(k, 30 * 86400)
            if hit and hit["dados"]:
                return dict(hit["dados"])
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError) as exc:  # cache é otimização; sem ele, consulta direto
            logger.debug("cache de site indisponível: %s", exc)
            cache = None
    fetch = fetch or _fetch_padrao
    status, html, url_ok = None, "", ""
    for url in (f"https://{dominio}", f"https://www.{dominio}", f"http://{dominio}"):
        status, html = fetch(url)
        if status and 200 <= status < 400 and html:
            url_ok = url
            break
    if not url_ok:
        return {"estado": "fora_do_ar", "dominio": dominio, "http": status, "redes": []}
    a = analisar_pagina(html, cnpj=cnpj, razao=razao, logradouro=logradouro)
    estado = ("cita_cnpj" if a["cita_cnpj"] else "cita_nome_ou_endereco"
              if (a["cita_razao"] or a["cita_endereco"]) else "sem_mencao")
    out = {"estado": estado, "dominio": dominio, "url": url_ok, "http": status, **a}
    if cache is not None:
        try:
            from compliance_agent.providers.base import Resultado, agora_iso
            cache.set(k, Resultado(True, out, "site", agora_iso()))
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError) as exc:
            logger.debug("cache de site não gravado: %s", exc)
    return out


def site_em_cache(dominio: str, cnpj: str) -> dict | None:
    """Só lê o cache (sem rede) — para produtos interativos (Lex, dossiê) não dispararem visitas."""
    try:
        from compliance_agent.providers.base import CacheSQLite
        cache = CacheSQLite()
        hit = cache.get(cache.chave("site:empresa", {"d": dominio, "c": cnpj}), 30 * 86400)
        return dict(hit["dados"]) if hit and hit["dados"] else None
    except (sqlite3.Error, OSError, ValueError, KeyError, TypeError) as exc:
        logger.debug("cache de site indisponível: %s", exc)
        return None


# ── combinação ────────────────────────────────────────────────────────────────────────────────

_INOCENTE = ("Cada validador tem explicação inocente própria: foto de rua pode ser antiga ou do lote vizinho; "
             "CEP pode ter mudado de logradouro; telefone/sala compartilhados são comuns em centro empresarial "
             "e contabilidade; empresa pequena muitas vezes não tem site. Só a convergência de fontes "
             "independentes sustenta indício — e indício não é acusação.")


def veredito_combinado(*, foto: str | None = None, cep: bool | None = None, telefone_compartilhado: int = 0,
                       sala_compartilhada: int = 0, site: str | None = None, osm_sem_edificacao: bool | None = None,
                       inexistente_de_fato: bool = False, rede_propria: bool = False) -> dict:
    """Soma os validadores. Cada argumento None/0 = não apurado (não conta nem a favor nem contra)."""
    susp: list[tuple[str, int]] = []
    subst: list[tuple[str, int]] = []
    avaliados = 0
    if inexistente_de_fato:
        susp.append(("Receita declarou INEXISTÊNCIA DE FATO", 4))
    if foto is not None:
        avaliados += 1
        if foto == "INDICIO":
            susp.append(("foto do lote provado mostra terreno/mato", 3))
        elif foto == "AFASTADO":
            subst.append(("foto do lote provado mostra edificação", 2))
    if cep is not None:
        avaliados += 1
        if cep is False:
            susp.append(("logradouro declarado não confere com o do CEP", 1))
    if telefone_compartilhado and 2 <= telefone_compartilhado <= 20:
        avaliados += 1
        # nº de OUTROS grupos econômicos (cnpj_basico ≠) com o mesmo telefone. Prevalência medida em 2.000
        # credores: ≥1 outro grupo em 33%, 2–20 em 12,7% — por isso peso 1 e nunca sozinho.
        susp.append((f"telefone da Receita repetido em {telefone_compartilhado} outros grupos empresariais", 1))
    if sala_compartilhada:
        avaliados += 1
        susp.append((f"mesma sala com {sala_compartilhada} outra(s) empresa(s)", 1))
    if site is not None:
        avaliados += 1
        if site == "cita_cnpj":
            subst.append(("site próprio cita o CNPJ", 3))
        elif site == "cita_nome_ou_endereco":
            subst.append(("site próprio cita a razão/endereço", 1))
        # site fora do ar / sem menção NÃO é suspeita: medido em 60 credores com domínio próprio
        # (14/11/2026), 55% caem aí (23% fora do ar, 32% sem citar a empresa) — mede a web, não a fachada.
    if osm_sem_edificacao is not None:
        avaliados += 1
        if osm_sem_edificacao:
            susp.append(("nenhuma edificação no ponto em região mapeada no OSM", 2))
    if rede_propria:
        avaliados += 1
        subst.append(("rede de filiais próprias", 1))
    if not avaliados and not inexistente_de_fato:
        return {"grau": "⚪", "saldo": 0, "suspeita": [], "substancia": [], "explicacao_inocente": _INOCENTE,
                "resumo": "nenhum validador apurado — INDISPONÍVEL não é 'regular'"}
    saldo = sum(p for _, p in susp) - sum(p for _, p in subst)
    n_fontes = len(susp)
    if n_fontes >= 2 and saldo >= 6:
        grau = "🔴"
    elif (n_fontes >= 2 and saldo >= 2) or (inexistente_de_fato and saldo >= 2):
        grau = "🟡"
    else:
        grau = "🟢"
    return {"grau": grau, "saldo": saldo, "suspeita": [s for s, _ in susp], "substancia": [s for s, _ in subst],
            "explicacao_inocente": _INOCENTE,
            "resumo": (f"{n_fontes} sinal(is) de suspeita, {len(subst)} de substância; saldo {saldo}"
                       + ("" if n_fontes >= 2 else " — sinal isolado não sustenta indício"))}
