"""
JFN Stock Agent — B3 market scanner with WhatsApp alerts and self-learning.

Modes:
    python agent.py                     # live mode (market hours, seg–sex 10h–17h BRT)
    python agent.py --test              # force immediate scan (ignores market hours)
    python agent.py --ticker WEGE3      # analyse a single ticker and print result
    python agent.py --backtest          # run 2-year historical backtest
    python agent.py --backtest --quick  # quick backtest (first 20 tickers)
    python agent.py --learn             # relearn weights from existing results
    python agent.py --stats             # show live signal outcome statistics
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
import learner
from notifier import send_whatsapp
from scorer import compute_score, format_signal_message
import tracker

ALL_TICKERS = list(dict.fromkeys(IBOVESPA_TICKERS + SMLL_TICKERS))

PHONE = os.getenv("WHATSAPP_PHONE", "")
BRT = pytz.timezone("America/Sao_Paulo")
SENT_SIGNALS_FILE = Path(__file__).parent / "sent_signals.json"


# ---------------------------------------------------------------------------
# Signal cooldown persistence
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
# Market hours
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
    w = learner.load_weights()
    n_sig = w.get("meta", {}).get("n_signals", 0)
    wr = w.get("meta", {}).get("baseline_win_rate")
    learn_info = f"modelo:{n_sig}sig win:{wr*100:.0f}%" if wr else "pesos padrão"

    print(f"\n{'='*58}")
    print(f"  JFN Scan — {ts}")
    print(f"  {len(ALL_TICKERS)} ações | limiar {SIGNAL_THRESHOLD}/100 | {learn_info}")
    print(f"{'='*58}")

    # Check outcomes of previously sent live signals (and trigger re-learning if any resolved)
    resolved = tracker.check_outcomes()
    if resolved:
        print(f"[agent] {resolved} sinal(is) live resolvido(s) — pesos atualizados.")

    sent = _load_sent()
    signals_sent = 0

    print("[agent] Buscando fundamentais (brapi.dev)...")
    fundamentals = get_fundamentals(ALL_TICKERS)

    for ticker in ALL_TICKERS:
        if signals_sent >= MAX_SIGNALS_PER_SCAN:
            print(f"[agent] Limite de {MAX_SIGNALS_PER_SCAN} sinais por scan atingido.")
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
                    now_str = datetime.now(BRT).isoformat()
                    sent[ticker] = now_str
                    _save_sent(sent)
                    signals_sent += 1

                    # Register for outcome tracking (feeds back into learning)
                    price = tech.get("current_price") or fund_raw.get("current_price") or 0.0
                    tracker.register_signal(
                        ticker=ticker,
                        entry_price=price,
                        score=score,
                        tech=tech,
                        fund_raw=fund_raw,
                        fund_score=fund.get("fundamental_score", 50),
                        sent_score=sentiment.get("sentiment_score", 60),
                    )

                    time.sleep(3)

        except Exception as exc:
            print(f"  [!] {ticker}: {exc}")

        time.sleep(0.4)

    print(f"\n[agent] Scan concluído — {signals_sent} sinal(is) enviado(s).\n")


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
# Stats display
# ---------------------------------------------------------------------------

def show_stats() -> None:
    stats = tracker.get_stats()
    w = learner.load_weights()
    meta = w.get("meta", {})

    print("\n" + "=" * 45)
    print("  JFN — Desempenho dos sinais live")
    print("=" * 45)
    print(f"  Total registrados: {stats['total']}")
    print(f"  Pendentes        : {stats['pending']}")
    print(f"  Resolvidos       : {stats['resolved']}")
    if stats["resolved"] > 0:
        print(f"  Wins (T1/T2)     : {stats['wins']}")
        print(f"  Stops            : {stats['stops']}")
        print(f"  Win rate         : {stats['win_rate']*100:.1f}%")
        print(f"  Retorno médio    : {stats['avg_return']*100:+.2f}%")

    print("\n" + "-" * 45)
    print("  Pesos do modelo atual")
    print("-" * 45)
    source = meta.get("source", "defaults")
    if source == "learned":
        print(f"  Baseado em {meta.get('n_signals', 0)} sinais históricos")
        print(f"  Win rate base: {meta.get('baseline_win_rate', 0)*100:.1f}%")
        iw = w.get("indicator_weights", {})
        for name, val in sorted(iw.items(), key=lambda x: -x[1]):
            print(f"    {name:<22}: {val:.0%}")
    else:
        print("  Usando pesos padrão (execute --backtest + --learn para calibrar)")

    tl = w.get("top_level_weights", {})
    print(f"\n  Técnico:{tl.get('technical', 0.5):.0%}  "
          f"Fundamental:{tl.get('fundamental', 0.35):.0%}  "
          f"Sentimento:{tl.get('sentiment', 0.15):.0%}")
    print("=" * 45 + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="JFN Stock Agent")
    parser.add_argument("--test", action="store_true", help="Força scan imediato")
    parser.add_argument("--ticker", metavar="T", help="Analisa um ticker e sai")
    parser.add_argument("--backtest", action="store_true", help="Roda backtest 2 anos")
    parser.add_argument("--quick", action="store_true", help="(com --backtest) só 20 tickers")
    parser.add_argument("--learn", action="store_true", help="Reatualiza pesos de aprendizado")
    parser.add_argument("--stats", action="store_true", help="Mostra estatísticas de sinais live")
    args = parser.parse_args()

    # --- One-shot commands ---
    if args.backtest:
        from backtester import ALL_TICKERS as BT_TICKERS, run_backtest
        tickers = BT_TICKERS[:20] if args.quick else None
        run_backtest(tickers)
        print("[agent] Rodando learner com os resultados do backtest...")
        learner.learn(verbose=True)
        return

    if args.learn:
        learner.learn(verbose=True)
        return

    if args.stats:
        show_stats()
        return

    if args.ticker:
        analyse_one(args.ticker.upper())
        return

    # --- Live / test mode ---
    if not PHONE:
        print("ERRO: defina WHATSAPP_PHONE no arquivo .env")
        sys.exit(1)

    if args.test:
        scan(force=True)
        return

    print("=" * 58)
    print("  JFN Stock Agent — modo live")
    print(f"  Universo: {len(ALL_TICKERS)} ações (IBOV + SMLL)")
    print(f"  Horário : {MARKET_OPEN_HOUR}h–{MARKET_CLOSE_HOUR}h BRT | seg–sex")
    print(f"  Intervalo: a cada {CHECK_INTERVAL_MINUTES} min")
    print(f"  Limiar  : {SIGNAL_THRESHOLD}/100")
    print(f"  WhatsApp: {PHONE}")
    print("=" * 58)

    scan()
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(scan)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
