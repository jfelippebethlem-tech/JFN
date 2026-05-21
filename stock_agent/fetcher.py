"""Fetches stock data from yfinance and brapi.dev."""

import os
import time
import requests
import feedparser
import pandas as pd
import yfinance as yf
from config import BRAPI_BASE_URL

BRAPI_TOKEN = os.getenv("BRAPI_TOKEN", "")


def get_price_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Fetch OHLCV daily history from yfinance."""
    try:
        df = yf.download(
            f"{ticker}.SA",
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            return df
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        return df
    except Exception as e:
        print(f"[fetcher] yfinance error for {ticker}: {e}")
        return pd.DataFrame()


def get_fundamentals(tickers: list[str]) -> dict[str, dict]:
    """Fetch fundamental data from brapi.dev in batches of 10."""
    results: dict[str, dict] = {}
    token_param = f"&token={BRAPI_TOKEN}" if BRAPI_TOKEN else ""

    for i in range(0, len(tickers), 10):
        batch = tickers[i : i + 10]
        batch_str = ",".join(batch)
        try:
            url = f"{BRAPI_BASE_URL}/quote/{batch_str}?fundamental=true{token_param}"
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("results", []):
                sym = item.get("symbol", "").replace(".SA", "")
                dy_raw = item.get("dividendYield")
                roe_raw = item.get("returnOnEquity")
                results[sym] = {
                    "name": item.get("longName") or item.get("shortName", sym),
                    "sector": item.get("sector", ""),
                    "current_price": item.get("regularMarketPrice"),
                    "pe": item.get("priceEarnings"),
                    "pb": item.get("priceToBook"),
                    "roe": roe_raw,
                    "dy": dy_raw,
                    "debt_ebitda": item.get("netDebtEbitda"),
                }
        except Exception as e:
            print(f"[fetcher] fundamentals error for batch {batch}: {e}")
        time.sleep(0.3)  # brapi.dev rate limit

    return results


def get_news(ticker: str) -> list[dict]:
    """Fetch recent Google News headlines for a ticker."""
    query = f"{ticker} ações B3 bolsa"
    url = (
        f"https://news.google.com/rss/search"
        f"?q={query}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    )
    try:
        feed = feedparser.parse(url)
        return [
            {
                "title": e.get("title", ""),
                "summary": e.get("summary", ""),
            }
            for e in feed.entries[:10]
        ]
    except Exception:
        return []
