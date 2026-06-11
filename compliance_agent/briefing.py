# -*- coding: utf-8 -*-
"""
Dados confiáveis para a rotina "BOM DIA DO MESTRE JORGE" — para o Yoda PARAR de raspar HTML frágil.

Fontes robustas (sem chave, JSON/RSS):
  - **Clima** (Barra da Tijuca/RJ): API Open-Meteo (gratuita, sem chave).
  - **Mercado** (dólar, Ibovespa, ouro, petróleo WTI): preços reais do Massare (`massare/data/massare.db`),
    com valor + variação do dia.
  - **Notícias** (5 Brasil + 5 Rio): Google News RSS.

Endpoint: `GET /api/briefing/dados` -> {clima, mercado, noticias}. O Yoda chama 1 vez e só formata + acrescenta
a piada e o versículo. Nada de scraping de climatempo/g1/infomoney (que falhava: grep vazio, 301, captcha).
"""
from __future__ import annotations

import json
import re
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

_MAX_IDADE_DIAS = 12  # notícia mais velha que isto é descartada (mata evergreen/2018 dos feeds)

_REPO = Path(__file__).resolve().parent.parent
_MASSARE_DB = _REPO / "massare" / "data" / "massare.db"

# Barra da Tijuca, RJ
_LAT, _LON = -23.01, -43.31

_WMO = {  # Open-Meteo weather codes -> PT
    0: "céu limpo", 1: "predomínio de sol", 2: "parcialmente nublado", 3: "nublado",
    45: "névoa", 48: "névoa com geada", 51: "garoa fraca", 53: "garoa", 55: "garoa forte",
    61: "chuva fraca", 63: "chuva", 65: "chuva forte", 71: "neve fraca", 73: "neve", 75: "neve forte",
    80: "pancadas de chuva", 81: "pancadas de chuva", 82: "pancadas fortes de chuva",
    95: "trovoadas", 96: "trovoadas com granizo", 99: "trovoadas com granizo",
}


def _http(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (JFN-Briefing)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        ct = r.headers.get_content_charset()
    if not ct:  # detecta encoding declarado no XML/HTML (Folha é ISO-8859-1, p.ex.)
        m = re.search(rb'encoding=["\']([\w-]+)["\']', raw[:200]) or re.search(rb'charset=["\']?([\w-]+)', raw[:600])
        ct = m.group(1).decode("ascii", "ignore") if m else None
    for enc in (ct, "utf-8", "latin-1"):
        if not enc:
            continue
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def clima_barra() -> dict:
    """Temp mín/máx e condição de hoje em Barra da Tijuca (Open-Meteo). {ok, min, max, condicao}."""
    try:
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={_LAT}&longitude={_LON}"
               "&daily=temperature_2m_max,temperature_2m_min,weather_code&timezone=America%2FSao_Paulo&forecast_days=1")
        d = json.loads(_http(url))
        dia = d["daily"]
        cod = int(dia["weather_code"][0])
        return {"ok": True, "min": round(dia["temperature_2m_min"][0]), "max": round(dia["temperature_2m_max"][0]),
                "condicao": _WMO.get(cod, "instável"), "cidade": "Barra da Tijuca, RJ", "fonte": "Open-Meteo"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erro": str(exc)[:80]}


def _preco(symbol: str) -> tuple:
    """(close_atual, var_pct) do símbolo na base do Massare. (None, None) se faltar."""
    if not _MASSARE_DB.exists():
        return None, None
    try:
        con = sqlite3.connect(str(_MASSARE_DB))
        rows = con.execute("SELECT close FROM prices WHERE symbol=? ORDER BY date DESC LIMIT 2", (symbol,)).fetchall()
        con.close()
        if not rows:
            return None, None
        atual = rows[0][0]
        if len(rows) > 1 and rows[1][0]:
            return atual, round((atual - rows[1][0]) / rows[1][0] * 100, 2)
        return atual, None
    except Exception:
        return None, None


def mercado() -> dict:
    """Dólar, Ibovespa, ouro e petróleo WTI com valor + variação do dia (fonte: Massare)."""
    defs = [
        ("dolar", "USDBRL=X", "Dólar comercial", "R$ {:.4f}", "https://www.infomoney.com.br/cotacoes/dolar-comercial/"),
        ("bovespa", "^BVSP", "Ibovespa", "{:,.0f} pts", "https://www.infomoney.com.br/cotacoes/b3/indice/ibovespa/"),
        ("ouro", "GC=F", "Ouro (oz)", "US$ {:,.2f}", "https://www.infomoney.com.br/cotacoes/commodities/ouro/"),
        ("petroleo_wti", "CL=F", "Petróleo WTI", "US$ {:.2f}", "https://www.infomoney.com.br/cotacoes/commodities/petroleo-wti/"),
    ]
    out = {}
    for chave, sym, nome, fmt, link in defs:
        v, var = _preco(sym)
        out[chave] = {
            "nome": nome,
            "valor": (fmt.format(v).replace(",", "X").replace(".", ",").replace("X", ".") if v is not None else "—"),
            "variacao_pct": var, "link": link,
        }
    return out


# RSS de SEÇÕES DE POLÍTICA dos principais veículos (URL real do veículo, não o redirect do Google News).
# (url, fonte, ja_e_politica): feeds de seção política aceitam tudo; feeds gerais do RJ são FILTRADOS por tema.
_FEEDS_BR = [
    ("https://g1.globo.com/rss/g1/politica/", "G1 Política", True),
    ("https://feeds.folha.uol.com.br/poder/rss091.xml", "Folha (Poder)", True),
    ("https://www.poder360.com.br/feed/", "Poder360", False),  # feed geral → exige tema político
    ("https://agenciabrasil.ebc.com.br/rss/politica/feed.xml", "Agência Brasil", True),
    ("https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/politica/?outputType=xml", "Estadão Política", True),
]
_FEEDS_RJ = [
    ("https://pox.globo.com/rss/g1/rio-de-janeiro/", "G1 Rio", False),
    ("https://oglobo.globo.com/rss/oglobo/rio/", "O Globo Rio", False),
    ("https://diariodorio.com/feed/", "Diário do Rio", False),
]

# Termos para FILTRAR notícias de política em feeds gerais (RJ) e priorizar relevância (acento-insensível).
_POL_KW = (
    "politic", "governo", "governador", "prefeit", "alerj", "camara", "vereador", "deputad",
    "eleic", "eleitor", "candidat", "tse", "stf", "stj", "senado", "congresso", "ministr",
    "secretari", "orcamento", "lei ", "projeto de lei", "votac", "cpi", "ministerio publico",
    "mp ", "tce", "tribunal de contas", "operacao", "investigac", "corrupc", "licitac",
    "verba", "emenda", "partido", "campanha", "urna", "impeachment", "decreto", "assembleia",
)
# Ruído a descartar (esporte/entretenimento/serviço), mesmo se passar no filtro político.
_NOISE_KW = (
    "futebol", "flamengo", "vasco", "fluminense", "botafogo", "libertadores", "brasileirao",
    "novela", "bbb", "horoscopo", "signos", "celebridad", "famoso", "receita de", "culinaria",
    "o que fazer", "rio open", "carnaval bloco", "lotec", "mega-sena", "loteria",
    "copa", "mundial", "brasil joga", "selecao", "jogo do brasil", "o que abre e o que fecha",
)

# Proxy de bypass de paywall (pedido do dono): toda URL de notícia é reescrita para isto.
_SEMPAYWALL = "https://sempaywall.com/{}"


def _limpa(s: str) -> str:
    s = re.sub(r"<!\[CDATA\[|\]\]>", "", s or "")
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _sem_acento(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _url_real(link: str) -> str:
    """URL real e limpa do veículo: resolve o redirect da Folha e tira parâmetros de rastreio."""
    link = (link or "").strip()
    if "redir.folha.com.br" in link and "*http" in link:
        link = "http" + link.split("*http", 1)[1]  # tudo após o '*' é a URL real
    link = re.split(r"[?#]", link, 1)[0]  # remove utm_/gclid/etc.
    return link


def _sempaywall(url: str) -> str:
    return _SEMPAYWALL.format(url)


def _relevante(titulo: str, link: str, ja_politica: bool) -> bool:
    blob = _sem_acento(f"{titulo} {link}")
    if any(n in blob for n in _NOISE_KW):
        return False
    if ja_politica:
        return True  # feed já é de seção política
    return any(k in blob for k in _POL_KW)  # feed geral (RJ): exige tema político


def _quando(bloco: str):
    """Data de publicação do item (RFC822). None se ausente/inválida."""
    m = re.search(r"<pubDate>(.*?)</pubDate>", bloco, re.S) or re.search(r"<dc:date>(.*?)</dc:date>", bloco, re.S)
    if not m:
        return None
    try:
        dt = parsedate_to_datetime(m.group(1).strip())
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(m.group(1).strip()).astimezone(timezone.utc)
        except ValueError:
            return None


def _feed(url: str, fonte: str, ja_politica: bool, n: int) -> list:
    try:
        xml = _http(url, timeout=12)
    except Exception:
        return []
    corte = datetime.now(timezone.utc) - timedelta(days=_MAX_IDADE_DIAS)
    itens = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, re.S):
        b = m.group(1)
        t = re.search(r"<title>(.*?)</title>", b, re.S)
        l = re.search(r"<link>(.*?)</link>", b, re.S)
        d = re.search(r"<description>(.*?)</description>", b, re.S)
        titulo = _limpa(t.group(1)) if t else ""
        link = _url_real(l.group(1) if l else "")
        tl = titulo.lower()
        if not titulo or not link.startswith("http"):
            continue
        if tl.startswith(("vídeos:", "videos:")) or "ao vivo" in tl or any(
                seg in link for seg in ("/ao-vivo/", "/videos", "/playlist/", "/podcast/")):
            continue
        if not _relevante(titulo, link, ja_politica):
            continue
        quando = _quando(b)
        if quando and quando < corte:
            continue  # descarta evergreen/antigo (ex.: itens de 2018 no feed do G1 Rio)
        itens.append({
            "titulo": titulo, "url": _sempaywall(link), "url_real": link, "fonte": fonte,
            "resumo": _limpa(d.group(1))[:400] if d else "", "_quando": quando,
        })
    itens.sort(key=lambda it: it.get("_quando") or corte, reverse=True)  # mais recentes primeiro
    return itens[:n]


def _texto_artigo(url: str, limite: int = 1800) -> str:
    """Baixa a notícia e extrai o CORPO (íntegra) — insumo p/ a rotina RACIOCINAR (não é o resumo final)."""
    try:
        html = _http(url, timeout=10)
    except Exception:
        return ""
    html = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", html)
    ps = re.findall(r'<p[^>]*class="[^"]*content-text__container[^"]*"[^>]*>(.*?)</p>', html, re.S)
    if not ps:
        ps = re.findall(r"<p[^>]*>(.*?)</p>", html, re.S)
    out = []
    for p in ps:
        t = _limpa(p)
        if len(t) < 30 or any(j in t for j in ("glb.", "cdnConfig", "function(", "{", "var ", "©")):
            continue
        out.append(t)
    return re.sub(r"\s+", " ", " ".join(out))[:limite]


def _dedup(itens: list) -> list:
    visto, out = set(), []
    for it in itens:
        dom = re.sub(r"^https?://(www\.)?", "", it["url_real"]).split("/")[0]
        chave = (dom, _sem_acento(it["titulo"])[:60])
        if chave in visto:
            continue
        visto.add(chave)
        out.append(it)
    return out


def _coletar(feeds: list, n: int) -> list:
    por_fonte = [_feed(url, fonte, ja_pol, 4) for url, fonte, ja_pol in feeds]
    # round-robin entre as fontes p/ DIVERSIDADE (1ª de cada, depois 2ª de cada…) — evita "tudo do mesmo veículo".
    intercalado = []
    for i in range(max((len(x) for x in por_fonte), default=0)):
        for lst in por_fonte:
            if i < len(lst):
                intercalado.append(lst[i])
    cand = _dedup(intercalado)[:n]
    for it in cand:  # enriquece SÓ os escolhidos com a íntegra (p/ resumo raciocinado)
        it["texto"] = _texto_artigo(it["url_real"])
        it.pop("_quando", None)  # datetime não serializa em JSON
    return cand


def noticias() -> dict:
    """8 notícias de POLÍTICA (4 Brasil + 4 Rio) de fontes VARIADAS. `url` já vem via sempaywall (bypass de
    paywall); `url_real` é a do veículo. `texto` é a íntegra — a rotina deve LER e RACIOCINAR (resumo de até
    3 linhas, NÃO transcrever); `resumo` é a chamada do RSS (fallback se a íntegra falhar)."""
    return {"brasil": _coletar(_FEEDS_BR, 4), "rio": _coletar(_FEEDS_RJ, 4)}


def dados() -> dict:
    """Pacote completo do briefing: clima + mercado + notícias (tudo de fontes confiáveis)."""
    return {"ok": True, "clima": clima_barra(), "mercado": mercado(), "noticias": noticias()}


if __name__ == "__main__":
    print(json.dumps(dados(), ensure_ascii=False, indent=1))
