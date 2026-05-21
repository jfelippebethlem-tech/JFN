"""
JFN Stock Agent — B3 market scanner with WhatsApp alerts.

Scans IBOVESPA + SMLL stocks for high-conviction buy signals using
technical, fundamental, and sentiment analysis. Sends alerts via
WhatsApp Web when a stock's combined score exceeds the threshold.

Usage:
    python agent.py              # Live mode (runs during market hours)
    python agent.py --test       # Scan now, ignore market hours
    python agent.py --ticker WEGE3   # Analyse a single ticker and print result
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytz
import schedule
from dotenv import load_dotenv

load_dotenv()

from analyzer import analyze_fundamentals, analyze_sentiment, analyze_technical
from config import (
    CHECK_INTERVAL_MINUTES,
    COOLDOWN_HOURS,
    IBOVESPA_TICKERS,
    MARKET_CLOSE_HOUR,
    MARKET_OPEN_HOUR,
    MAX_SIGNALS_PER_SCAN,
    SIGNAL_THRESHOLD,
    SMLL_TICKERS,
)
from fetcher import get_fundamentals, get_news, get_price_history
from notifier import send_whatsapp
from scorer import compute_score, format_signal_message

ALL_TICKERS = list(dict.fromkeys(IBOVESPA_TICKERS + SMLL_TICKERS))  # dedup, preserve order

PHONE = os.getenv("WHATSAPP_PHONE", "")
BRT = pytz.timezone("America/Sao_Paulo")
SENT_SIGNALS_FILE = Path(__file__).parent / "sent_signals.json"


# ---------------------------------------------------------------------------
# Signal persistence
# ---------------------------------------------------------------------------

def _load_sent() -> dict:
    if SENT_SIGNALS_FILE.exists():
        with open(SENT_SIGNALS_FILE) as f:
            return json.load(f)
    return {}


def _save_sent(sent: dict) -> None:
    with open(SENT_SIGNALS_FILE, "w") as f:
        json.dump(sent, f, indent=2, default=str)


def _can_send(ticker: str, sent: dict) -> bool:
    if ticker not in sent:
        return True
    last = datetime.fromisoformat(sent[ticker])
    return datetime.now(BRT) - last > timedelta(hours=COOLDOWN_HOURS)


# ---------------------------------------------------------------------------
# Market hours guard
# ---------------------------------------------------------------------------

def _is_market_open() -> bool:
    now = datetime.now(BRT)
    if now.weekday() >= 5:
        return False
    return MARKET_OPEN_HOUR <= now.hour < MARKET_CLOSE_HOUR


# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------

def scan(force: bool = False) -> None:
    if not force and not _is_market_open():
        ts = datetime.now(BRT).strftime("%H:%M %d/%m")
        print(f"[agent] Mercado fechado — {ts}")
        return

    ts = datetime.now(BRT).strftime("%H:%M:%S %d/%m/%Y")
    print(f"\n{'='*55}")
    print(f"  JFN Scan — {ts}")
    print(f"  {len(ALL_TICKERS)} ações | limiar {SIGNAL_THRESHOLD}/100")
    print(f"{'='*55}")

    sent = _load_sent()
    signals_sent = 0

    print("[agent] Buscando dados fundamentalistas (brapi.dev)...")
    fundamentals = get_fundamentals(ALL_TICKERS)

    for ticker in ALL_TICKERS:
        if signals_sent >= MAX_SIGNALS_PER_SCAN:
            print(f"[agent] Limite de {MAX_SIGNALS_PER_SCAN} sinais atingido.")
            break

        if not _can_send(ticker, sent):
            continue

        try:
            df = get_price_history(ticker)
            if df.empty or len(df) < 50:
                continue

            tech = analyze_technical(df)
            if not tech:
                continue

            fund_raw = fundamentals.get(ticker, {})
            fund = analyze_fundamentals(fund_raw)
            news = get_news(ticker)
            sentiment = analyze_sentiment(news)

            score, conviction = compute_score(tech, fund, sentiment)
            bar = "█" * int(score / 5)
            print(f"  {ticker:8s} {score:5.1f}/100  {bar}")

            if score >= SIGNAL_THRESHOLD:
                msg = format_signal_message(ticker, tech, fund, sentiment, score, conviction, fund_raw)
                print(f"\n  ★ SINAL: {ticker} ({score:.1f}) — {conviction}")

                if send_whatsapp(PHONE, msg):
                    sent[ticker] = datetime.now(BRT).isoformat()
                    _save_sent(sent)
                    signals_sent += 1
                    time.sleep(3)  # brief pause between messages

        except Exception as exc:
            print(f"  [!] {ticker}: {exc}")

        time.sleep(0.4)  # yfinance / brapi rate limit

    print(f"\n[agent] Fim do scan — {signals_sent} sinal(is) enviado(s).\n")


# ---------------------------------------------------------------------------
# Single-ticker debug
# ---------------------------------------------------------------------------

def analyse_one(ticker: str) -> None:
    print(f"\n[agent] Analisando {ticker}...")
    df = get_price_history(ticker)
    if df.empty:
        print(f"  Sem dados para {ticker}")
        return

    tech = analyze_technical(df)
    fund_raw = get_fundamentals([ticker]).get(ticker, {})
    fund = analyze_fundamentals(fund_raw)
    news = get_news(ticker)
    sentiment = analyze_sentiment(news)
    score, conviction = compute_score(tech, fund, sentiment)

    msg = format_signal_message(ticker, tech, fund, sentiment, score, conviction, fund_raw)
    print(msg)
    print(f"\n→ Score: {score}/100 | {conviction}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="JFN Stock Agent")
    parser.add_argument("--test", action="store_true", help="Run scan now, ignore market hours")
    parser.add_argument("--ticker", metavar="TICKER", help="Analyse a single ticker and exit")
    args = parser.parse_args()

    if not PHONE and not args.ticker:
        print("ERRO: defina WHATSAPP_PHONE no arquivo .env")
        sys.exit(1)

    if args.ticker:
        analyse_one(args.ticker.upper())
        return

    if args.test:
        scan(force=True)
        return

    print("=" * 55)
    print("  JFN Stock Agent — iniciando modo live")
    print(f"  Universo: {len(ALL_TICKERS)} ações (IBOV + SMLL)")
    print(f"  Horário: {MARKET_OPEN_HOUR}h–{MARKET_CLOSE_HOUR}h BRT | seg–sex")
    print(f"  Intervalo: a cada {CHECK_INTERVAL_MINUTES} min")
    print(f"  Limiar de sinal: {SIGNAL_THRESHOLD}/100")
    print(f"  WhatsApp: {PHONE}")
    print("=" * 55)

    scan()  # immediate first run
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(scan)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
