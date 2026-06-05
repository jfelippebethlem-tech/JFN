# -*- coding: utf-8 -*-
"""
Massare — fontes de dados GRATUITAS e sem chave (validadas desta VM em 2026-06-05).

  Yahoo Finance (chart API) ... ações, índices, commodities (futuros), FX, cripto. ~20 anos diários.
  BCB / SGS .................... macro Brasil: PTAX dólar (1), Selic meta (432), IPCA (433)...
  FRED (CSV) ................... macro EUA sem chave: DGS10 (treasury 10y), DFF (fed funds), etc.
  Stooq (CSV) .................. fallback/histórico longo (ex.: ^spx, ^ndq).
  CoinGecko .................... cripto ao vivo (fallback).

Regra Massare: NUNCA inventar cotação. Cada ponto carrega a fonte. Em falha, retornar vazio
(o chamador decide usar cache), nunca um número fabricado.
"""
import csv
import io
import time
import httpx

UA = {"User-Agent": "Mozilla/5.0 (compatible; MassareBot/1.0)"}


def _get(url, **kw):
    last = None
    for attempt in range(3):
        try:
            r = httpx.get(url, headers=UA, timeout=40, follow_redirects=True, **kw)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET falhou: {url} ({last})")


# ----------------------------------------------------------------------------- Yahoo
def yahoo_history(symbol, rng="20y", interval="1d"):
    """Retorna lista de dicts OHLCV {symbol,date,open,high,low,close,adj_close,volume}."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{httpx.URL(symbol)}"
           f"?range={rng}&interval={interval}&events=div%2Csplit")
    j = _get(url).json()["chart"]["result"][0]
    ts = j.get("timestamp") or []
    q = j["indicators"]["quote"][0]
    adj = (j["indicators"].get("adjclose") or [{}])[0].get("adjclose") or [None] * len(ts)
    out = []
    for i, t in enumerate(ts):
        date = time.strftime("%Y-%m-%d", time.gmtime(t))
        row = {"symbol": symbol, "date": date,
               "open": q["open"][i], "high": q["high"][i], "low": q["low"][i],
               "close": q["close"][i], "adj_close": adj[i], "volume": q["volume"][i]}
        if row["close"] is None:
            continue
        out.append(row)
    return out


# ----------------------------------------------------------------------------- BCB / SGS
def bcb_series(code, last_n=None):
    """Série do SGS do Banco Central. Retorna [(date 'YYYY-MM-DD', value), ...]."""
    base = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
    url = base + (f"/ultimos/{last_n}?formato=json" if last_n else "?formato=json")
    data = _get(url).json()
    out = []
    for d in data:
        try:
            dd = d["data"]  # dd/mm/aaaa
            iso = f"{dd[6:10]}-{dd[3:5]}-{dd[0:2]}"
            out.append((iso, float(d["valor"])))
        except Exception:
            continue
    return out


# ----------------------------------------------------------------------------- FRED (CSV, sem chave)
def fred_series(series_id):
    """Série do FRED via CSV público (sem API key). [(date, value), ...]."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    txt = _get(url).text
    out = []
    for row in csv.DictReader(io.StringIO(txt)):
        date = row.get("DATE") or row.get("observation_date")
        val = row.get(series_id) or list(row.values())[-1]
        if not date or val in (".", "", None):
            continue
        try:
            out.append((date, float(val)))
        except ValueError:
            continue
    return out


# ----------------------------------------------------------------------------- Stooq (fallback)
def stooq_history(symbol):
    """Histórico diário do Stooq via CSV. symbol ex.: '^spx', '^ndq', 'aapl.us'."""
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    txt = _get(url).text
    out = []
    for row in csv.DictReader(io.StringIO(txt)):
        if not row.get("Date"):
            continue
        try:
            out.append({"symbol": symbol, "date": row["Date"],
                        "open": float(row["Open"]), "high": float(row["High"]),
                        "low": float(row["Low"]), "close": float(row["Close"]),
                        "adj_close": float(row["Close"]),
                        "volume": float(row.get("Volume") or 0)})
        except (ValueError, KeyError):
            continue
    return out


# ----------------------------------------------------------------------------- CoinGecko (live)
def coingecko_price(ids="bitcoin,ethereum", vs="usd,brl"):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies={vs}&include_24hr_change=true"
    return _get(url).json()
