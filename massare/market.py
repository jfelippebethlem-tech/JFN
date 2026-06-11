# -*- coding: utf-8 -*-
"""
Massare — ciclo de PREGÃO (intraday) multi-horizonte.

Diferente do `daily.py` (que roda 1x/dia e REGISTRA a previsão oficial no placar), este módulo roda
repetidamente DURANTE o pregão (09:50 BRT pré-market → ~18:00 BRT fechamento, via `massare-market.timer`)
e produz uma fotografia AO VIVO de cenários em 4 horizontes — **sem** poluir o placar (record=False):

    curtíssimo (≤1 pregão) · curto (~1 semana) · médio (~1 mês) · longo (~1 trimestre)

A cada execução: atualiza preços recentes + sentimento, coleta manchetes de mercado (best-effort),
calcula a direção do ensemble por horizonte para o núcleo de ativos (BR+EUA+câmbio+commodities+cripto),
e grava o snapshot em `massare/data/market_snapshot.json`. A API do JFN (`/api/massare/cenarios`) lê esse
snapshot para o Yoda responder o Mestre Jorge na hora.

USO (CLI):
    cd ~/JFN && .venv/bin/python -m massare.market            # roda 1 ciclo e imprime o briefing
    cd ~/JFN && .venv/bin/python -m massare.market --json     # imprime o snapshot em JSON
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from pathlib import Path

from massare import behavior, engine, learning, store

# horizonte (em pregões) por faixa de prazo + rótulo amigável
HORIZONS = OrderedDict([("curtissimo", 1), ("curto", 5), ("medio", 21), ("longo", 63)])
HORIZ_LABEL = {"curtissimo": "≤ 1 pregão", "curto": "~ 1 semana", "medio": "~ 1 mês", "longo": "~ 1 trimestre"}

# núcleo de ativos acompanhados no pregão (BR + EUA + câmbio + commodities + cripto)
NUCLEO = ["^BVSP", "^GSPC", "^IXIC", "^DJI", "GC=F", "CL=F", "DX-Y.NYB", "USDBRL=X", "NVDA", "BTC-USD", "ETH-USD"]
NOMES = {
    "^BVSP": "Ibovespa", "^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow Jones",
    "GC=F": "Ouro", "CL=F": "Petróleo WTI", "DX-Y.NYB": "Índice Dólar (DXY)",
    "USDBRL=X": "Dólar/Real", "NVDA": "NVIDIA", "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum",
}

_SNAPSHOT = Path(__file__).resolve().parent / "data" / "market_snapshot.json"

# Nome amigável (PT) → símbolo yfinance. Evita o erro do Yoda (ex.: pedir "prata" virava "XAG=F" inválido).
_ALIAS_SYMBOL = {
    "prata": "SI=F", "silver": "SI=F", "xag": "SI=F", "xag=f": "SI=F",
    "ouro": "GC=F", "gold": "GC=F", "xau": "GC=F",
    "cobre": "HG=F", "copper": "HG=F",
    "petroleo": "CL=F", "petróleo": "CL=F", "wti": "CL=F", "oil": "CL=F", "brent": "BZ=F",
    "gas": "NG=F", "gás": "NG=F", "milho": "ZC=F", "soja": "ZS=F",
    "bitcoin": "BTC-USD", "btc": "BTC-USD", "ethereum": "ETH-USD", "eth": "ETH-USD",
    "dolar": "DX-Y.NYB", "dólar": "DX-Y.NYB", "dxy": "DX-Y.NYB", "real": "USDBRL=X", "usdbrl": "USDBRL=X",
    "ibovespa": "^BVSP", "ibov": "^BVSP", "bovespa": "^BVSP", "bolsa": "^BVSP",
    "sp500": "^GSPC", "s&p": "^GSPC", "s&p500": "^GSPC", "nasdaq": "^IXIC", "dow": "^DJI", "vix": "^VIX",
    "nvidia": "NVDA", "nvda": "NVDA",
}


def resolver_symbol(termo: str) -> str:
    """Resolve nome amigável PT → símbolo yfinance (prata→SI=F). Se já for símbolo, devolve como veio."""
    t = (termo or "").strip()
    return _ALIAS_SYMBOL.get(t.lower(), t)


# ───────────────────────────── pregão / horário ─────────────────────────────

def pregao_aberto(agora=None) -> bool:
    """Heurística simples: B3 dias úteis, ~09:50→18:10 BRT (12:50→21:10 UTC). Best-effort, não bloqueia."""
    t = agora or time.gmtime()
    if t.tm_wday >= 5:  # 5=sáb, 6=dom
        return False
    minutos_utc = t.tm_hour * 60 + t.tm_min
    return (12 * 60 + 50) <= minutos_utc <= (21 * 60 + 10)


# ───────────────────────────── coleta best-effort ─────────────────────────────

def _refresh_precos(symbols) -> int:
    upd = 0
    try:
        from massare import sources
        for sym in symbols:
            try:
                upd += store.upsert_prices(sources.yahoo_history(sym, rng="5d"), "yahoo")
            except Exception:
                pass
    except Exception:
        pass
    return upd


def noticias(consulta: str = "mercado financeiro Brasil bolsa dólar", max_itens: int = 8) -> list[dict]:
    """Manchetes via Google News RSS (grátis, sem chave). Best-effort: lista vazia se egress falhar."""
    try:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(consulta)
               + "&hl=pt-BR&gl=BR&ceid=BR:pt-419")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Massare)"})
        with urllib.request.urlopen(req, timeout=12) as r:
            xml = r.read().decode("utf-8", "replace")
        itens = []
        for m in list(re.finditer(r"<item>(.*?)</item>", xml, re.S))[:max_itens]:
            bloco = m.group(1)
            tit = re.search(r"<title>(.*?)</title>", bloco, re.S)
            fonte = re.search(r"<source[^>]*>(.*?)</source>", bloco, re.S)
            titulo = re.sub(r"<!\[CDATA\[|\]\]>", "", tit.group(1)).strip() if tit else ""
            if titulo:
                itens.append({"titulo": titulo, "fonte": (fonte.group(1).strip() if fonte else "")})
        return itens
    except Exception:
        return []


# ───────────────────────────── cenários multi-horizonte ─────────────────────────────

def _cenario_ativo(sym: str) -> dict:
    """Direção do ensemble por horizonte para um ativo. {curtissimo:{dir,prob,oos}, ...}."""
    out = {"symbol": sym, "nome": NOMES.get(sym, sym), "horizontes": OrderedDict()}
    votos_up = 0
    n = 0
    for faixa, hz in HORIZONS.items():
        try:
            p = engine.predict_today(sym, horizon=hz)
        except Exception as exc:  # noqa: BLE001
            out["horizontes"][faixa] = {"erro": str(exc)[:60]}
            continue
        if not p:
            out["horizontes"][faixa] = {"erro": "sem dados"}
            continue
        out["horizontes"][faixa] = {
            "prazo": HORIZ_LABEL[faixa], "direcao": p["direction"], "prob": p["prob"],
            "oos_hit_rate": p.get("ensemble_oos_hit_rate"), "asof": p.get("asof"),
        }
        n += 1
        votos_up += 1 if p["direction"] == "up" else 0
    if n:
        out["consenso"] = "alta" if votos_up > n / 2 else ("baixa" if votos_up < n / 2 else "misto")
    return out


def cenarios(symbols=None, record: bool = False) -> dict:
    """Roda 1 ciclo de pregão e GRAVA o snapshot. Retorna o snapshot."""
    store.init_db()
    symbols = symbols or NUCLEO
    ts = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    upd = _refresh_precos(symbols)
    try:
        behavior.collect()
    except Exception:
        pass

    ativos = [_cenario_ativo(s) for s in symbols]

    snap = {
        "ts": ts,
        "pregao_aberto": pregao_aberto(),
        "dados_atualizados": upd,
        "sentimento": _safe(behavior.snapshot),
        "regimes": _regimes(),
        "horizontes_legenda": HORIZ_LABEL,
        "ativos": ativos,
        "placar": _safe(learning.scoreboard),
        "noticias": noticias(),
    }
    try:
        _SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        _SNAPSHOT.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
        store.set_meta("last_market", ts)
    except Exception:
        pass
    return snap


def _safe(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return {"erro": str(exc)[:60]}


def _regimes():
    try:
        from massare import ml
        return {s: ml.regime_hmm(s).get("rotulo_atual") for s in ["^GSPC", "^BVSP", "BTC-USD"]}
    except Exception as exc:  # noqa: BLE001
        return {"erro": str(exc)[:60]}


def ler_snapshot() -> dict | None:
    """Lê o último snapshot salvo (para a API responder sem recomputar). None se não existir."""
    try:
        return json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    except Exception:
        return None


def briefing(snap: dict) -> str:
    fg = (snap.get("sentimento") or {}).get("fear_greed", {})
    linhas = ["📈 Massare — cenários de pregão", f"  {snap.get('ts')} (pregão {'ABERTO' if snap.get('pregao_aberto') else 'fechado'})"]
    if fg:
        linhas.append(f"  Sentimento: {fg.get('value')} ({fg.get('label','')})")
    for a in snap.get("ativos", []):
        hz = a.get("horizontes", {})
        def _seta(faixa):
            d = (hz.get(faixa) or {}).get("direcao")
            return "↑" if d == "up" else "↓" if d == "down" else "·"
        linhas.append(f"  {a['nome']:14} curt:{_seta('curtissimo')} cur:{_seta('curto')} "
                      f"méd:{_seta('medio')} lon:{_seta('longo')}  [{a.get('consenso','?')}]")
    nws = snap.get("noticias", [])
    if nws:
        linhas.append("  Notícias: " + " | ".join(n["titulo"][:60] for n in nws[:3]))
    return "\n".join(linhas)


def run() -> dict:
    snap = cenarios()
    return snap


if __name__ == "__main__":
    s = run()
    if "--json" in sys.argv:
        print(json.dumps(s, ensure_ascii=False, indent=1))
    else:
        print(briefing(s))
