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
import os
import re
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path

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
        return r.read().decode("utf-8", "replace")


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


def _noticias_rss(query: str, n: int) -> list:
    try:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
               + "&hl=pt-BR&gl=BR&ceid=BR:pt-419")
        xml = _http(url, timeout=12)
        itens = []
        for m in list(re.finditer(r"<item>(.*?)</item>", xml, re.S))[:n]:
            bloco = m.group(1)
            tit = re.search(r"<title>(.*?)</title>", bloco, re.S)
            link = re.search(r"<link>(.*?)</link>", bloco, re.S)
            fonte = re.search(r"<source[^>]*>(.*?)</source>", bloco, re.S)
            titulo = re.sub(r"<!\[CDATA\[|\]\]>", "", tit.group(1)).strip() if tit else ""
            if titulo:
                itens.append({"titulo": titulo, "url": (link.group(1).strip() if link else ""),
                              "fonte": (fonte.group(1).strip() if fonte else "")})
        return itens
    except Exception:
        return []


def noticias() -> dict:
    """10 notícias: 5 do Brasil + 5 do Rio de Janeiro (Google News RSS)."""
    return {"brasil": _noticias_rss("Brasil notícias", 5),
            "rio": _noticias_rss("Rio de Janeiro notícias", 5)}


def dados() -> dict:
    """Pacote completo do briefing: clima + mercado + notícias (tudo de fontes confiáveis)."""
    return {"ok": True, "clima": clima_barra(), "mercado": mercado(), "noticias": noticias()}


if __name__ == "__main__":
    print(json.dumps(dados(), ensure_ascii=False, indent=1))
