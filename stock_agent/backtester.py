"""
JFN Backtester — 2-year historical simulation of the signal algorithm.

Strategy:
- Entry price: close of the day *after* the signal (conservative, avoids hindsight)
- Targets: +8% (T1) and +15% (T2)
- Stop loss: -4%
- Evaluation window: up to 20 trading days forward
- Cooldown: skip ticker for 20 trading days after a signal

Indicators are computed once on the full series; row values are read
at each simulation step — no look-ahead, O(n) per ticker.

Usage:
    python backtester.py                  # full IBOV+SMLL run
    python backtester.py --quick          # first 20 tickers only
    python backtester.py --ticker WEGE3   # single ticker
"""

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator
from ta.volatility import BollingerBands

from config import IBOVESPA_TICKERS, SIGNAL_THRESHOLD, SMLL_TICKERS

ALL_TICKERS = list(dict.fromkeys(IBOVESPA_TICKERS + SMLL_TICKERS))
RESULTS_FILE = Path(__file__).parent / "backtest_results.json"

TARGET1 = 0.08
TARGET2 = 0.15
STOP = -0.04
EVAL_DAYS = 20
COOLDOWN_DAYS = 20


# ---------------------------------------------------------------------------
# Indicator computation (single-pass, no look-ahead)
# ---------------------------------------------------------------------------

def _build_indicator_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pre-compute all rolling indicators on the full price series.
    Values at row i use only data up to row i (rolling windows).
    """
    close = df["Close"].squeeze()
    volume = df["Volume"].squeeze()

    out = pd.DataFrame(index=df.index)
    out["close"] = close.values
    out["volume"] = volume.values

    out["rsi"] = RSIIndicator(close, window=14).rsi().values

    m = MACD(close)
    macd_line = m.macd()
    sig_line = m.macd_signal()
    out["macd"] = macd_line.values
    out["macd_sig"] = sig_line.values
    out["macd_cross"] = (
        (macd_line.shift(1) < sig_line.shift(1)) & (macd_line >= sig_line)
    ).values
    out["macd_bull"] = (macd_line >= sig_line).values

    bb = BollingerBands(close, window=20)
    out["bb_low"] = bb.bollinger_lband().values
    out["bb_mid"] = bb.bollinger_mavg().values
    out["bb_touch"] = (close <= bb.bollinger_lband() * 1.01).values

    out["ema9"] = EMAIndicator(close, window=9).ema_indicator().values
    out["ema21"] = EMAIndicator(close, window=21).ema_indicator().values
    out["ema50"] = EMAIndicator(close, window=50).ema_indicator().values
    ema200_series = EMAIndicator(close, window=200).ema_indicator()
    out["ema200"] = ema200_series.values
    out["ema_uptrend_long"] = (out["ema50"] > out["ema200"]).values
    out["ema_uptrend_short"] = (out["ema9"] > out["ema21"]).values

    vol_avg = volume.rolling(20).mean()
    vol_ratio = (volume / vol_avg).clip(upper=5)
    out["vol_ratio"] = vol_ratio.values

    return out.dropna()


def _score_row(row: pd.Series) -> float:
    """Score a single pre-computed indicator row (equal weights, 0–100)."""
    score = 0

    rsi = float(row["rsi"])
    if rsi < 30:
        score += 20
    elif rsi < 40:
        score += 15
    elif rsi < 50:
        score += 5

    if row["macd_cross"]:
        score += 20
    elif row["macd_bull"]:
        score += 10

    if row["bb_touch"]:
        score += 20
    elif float(row["close"]) <= float(row["bb_mid"]):
        score += 10

    uptrend_long = bool(row["ema_uptrend_long"])
    uptrend_short = bool(row["ema_uptrend_short"])
    if uptrend_long and uptrend_short:
        score += 20
    elif uptrend_long:
        score += 10
    elif uptrend_short:
        score += 5

    vr = float(row["vol_ratio"])
    if vr >= 2.0:
        score += 20
    elif vr >= 1.5:
        score += 12
    elif vr >= 1.0:
        score += 5

    return float(score)


def _combined_score(tech_score: float, fund_proxy: float = 55.0) -> float:
    """Blend technical + fundamental proxy + neutral sentiment."""
    return tech_score * 0.50 + fund_proxy * 0.35 + 60.0 * 0.15


def _evaluate_forward(closes: np.ndarray, entry_idx: int) -> dict:
    """
    Measure outcome of entering at entry_idx.
    Checks price path day-by-day for T1, T2, or stop.
    """
    n = len(closes)
    if entry_idx >= n:
        return {}

    entry = float(closes[entry_idx])
    t1_price = entry * (1 + TARGET1)
    t2_price = entry * (1 + TARGET2)
    stop_price = entry * (1 + STOP)

    res = {
        "entry_price": round(entry, 2),
        "return_5d": None,
        "return_10d": None,
        "return_20d": None,
        "hit_target1": False,
        "hit_target2": False,
        "hit_stop": False,
        "outcome": "expired",
        "days_to_outcome": None,
    }

    outcome_day = None
    for d in range(1, min(EVAL_DAYS + 1, n - entry_idx)):
        px = float(closes[entry_idx + d])
        ret = (px - entry) / entry

        if outcome_day is None:
            if px <= stop_price:
                res["hit_stop"] = True
                res["outcome"] = "stop"
                outcome_day = d
            elif px >= t2_price:
                res["hit_target1"] = True
                res["hit_target2"] = True
                res["outcome"] = "win_t2"
                outcome_day = d
            elif px >= t1_price:
                res["hit_target1"] = True
                res["outcome"] = "win_t1"
                outcome_day = d

        if d == 5:
            res["return_5d"] = round(ret, 4)
        if d == 10:
            res["return_10d"] = round(ret, 4)
        if d == 20:
            res["return_20d"] = round(ret, 4)

    res["days_to_outcome"] = outcome_day
    return res


# ---------------------------------------------------------------------------
# Per-ticker backtest
# ---------------------------------------------------------------------------

def _backtest_ticker(ticker: str, two_years_ago: pd.Timestamp) -> list[dict]:
    try:
        df = yf.download(
            f"{ticker}.SA",
            period="3y",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        if df.empty or len(df) < 220:
            return []
    except Exception:
        return []

    ind = _build_indicator_df(df)
    if ind.empty:
        return []

    # Align dates: only evaluate within the 2-year window, leave 21d buffer at end
    tz = ind.index.tz
    cutoff = two_years_ago.tz_localize(tz) if tz and two_years_ago.tzinfo is None else two_years_ago
    eval_mask = ind.index >= cutoff
    eval_rows = ind[eval_mask].iloc[:-21]  # need forward data
    if eval_rows.empty:
        return []

    closes = ind["close"].values
    all_idx = ind.index

    signals = []
    last_signal_row = -999

    for i, (date, row) in enumerate(eval_rows.iterrows()):
        abs_i = all_idx.get_loc(date)

        # Cooldown check
        if abs_i - last_signal_row < COOLDOWN_DAYS:
            continue

        tech_score = _score_row(row)
        combined = _combined_score(tech_score)

        if combined < SIGNAL_THRESHOLD:
            continue

        # Entry at next-day close
        entry_abs = abs_i + 1
        if entry_abs >= len(closes):
            continue

        outcome = _evaluate_forward(closes, entry_abs)
        if not outcome:
            continue

        signals.append(
            {
                "ticker": ticker,
                "signal_date": str(date.date()),
                "tech_score": round(tech_score, 1),
                "combined_score": round(combined, 1),
                "rsi": round(float(row["rsi"]), 1),
                "rsi_oversold": 1 if float(row["rsi"]) < 40 else 0,
                "macd_cross": int(bool(row["macd_cross"])),
                "macd_bull": int(bool(row["macd_bull"])),
                "bb_touch": int(bool(row["bb_touch"])),
                "ema_uptrend_long": int(bool(row["ema_uptrend_long"])),
                "ema_uptrend_short": int(bool(row["ema_uptrend_short"])),
                "vol_ratio": round(min(float(row["vol_ratio"]), 4.0), 2),
                **outcome,
            }
        )
        last_signal_row = abs_i

    return signals


# ---------------------------------------------------------------------------
# Summary and report
# ---------------------------------------------------------------------------

def _build_report(all_signals: list[dict]) -> dict:
    total = len(all_signals)
    if total == 0:
        report = {"meta": {"total_signals": 0, "run_date": datetime.now().isoformat()}, "signals": []}
        with open(RESULTS_FILE, "w") as f:
            json.dump(report, f, indent=2)
        return report

    wins_t1 = sum(1 for s in all_signals if s["hit_target1"])
    wins_t2 = sum(1 for s in all_signals if s["hit_target2"])
    stops = sum(1 for s in all_signals if s["hit_stop"])

    r5 = [s["return_5d"] for s in all_signals if s["return_5d"] is not None]
    r10 = [s["return_10d"] for s in all_signals if s["return_10d"] is not None]
    r20 = [s["return_20d"] for s in all_signals if s["return_20d"] is not None]

    # Per-ticker win rates
    ticker_stats: dict[str, dict] = {}
    for s in all_signals:
        t = s["ticker"]
        if t not in ticker_stats:
            ticker_stats[t] = {"total": 0, "wins": 0}
        ticker_stats[t]["total"] += 1
        if s["hit_target1"]:
            ticker_stats[t]["wins"] += 1

    best = max(ticker_stats, key=lambda t: ticker_stats[t]["wins"] / max(ticker_stats[t]["total"], 1))

    meta = {
        "run_date": datetime.now().isoformat(),
        "total_signals": total,
        "win_rate_t1": round(wins_t1 / total, 3),
        "win_rate_t2": round(wins_t2 / total, 3),
        "stop_rate": round(stops / total, 3),
        "avg_return_5d": round(float(np.mean(r5)), 4) if r5 else None,
        "avg_return_10d": round(float(np.mean(r10)), 4) if r10 else None,
        "avg_return_20d": round(float(np.mean(r20)), 4) if r20 else None,
        "best_ticker": best,
        "ticker_stats": ticker_stats,
    }

    report = {"meta": meta, "signals": all_signals}
    with open(RESULTS_FILE, "w") as f:
        json.dump(report, f, indent=2)

    _print_report(meta)
    return report


def _print_report(m: dict) -> None:
    n = m["total_signals"]
    print(f"\n{'='*58}")
    print(f"  RESULTADO DO BACKTEST — 2 anos | {n} sinais gerados")
    print(f"{'='*58}")
    print(f"  Win rate alvo +8%  (T1): {m['win_rate_t1']*100:.1f}%")
    print(f"  Win rate alvo +15% (T2): {m['win_rate_t2']*100:.1f}%")
    print(f"  Stop loss   -4%       : {m['stop_rate']*100:.1f}%")
    if m["avg_return_10d"]:
        print(f"  Retorno médio 10 dias  : {m['avg_return_10d']*100:+.2f}%")
    if m["avg_return_20d"]:
        print(f"  Retorno médio 20 dias  : {m['avg_return_20d']*100:+.2f}%")
    print(f"  Melhor ticker          : {m['best_ticker']}")
    print(f"  Resultados salvos em   : backtest_results.json")
    print(f"{'='*58}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_backtest(tickers: list[str] | None = None) -> dict:
    tickers = tickers or ALL_TICKERS
    two_years_ago = pd.Timestamp.now() - pd.DateOffset(years=2)

    print(f"\n{'='*58}")
    print(f"  JFN Backtester — {len(tickers)} tickers | limiar {SIGNAL_THRESHOLD}/100")
    print(f"  Período: {two_years_ago.strftime('%d/%m/%Y')} → hoje")
    print(f"{'='*58}\n")

    all_signals: list[dict] = []

    for i, ticker in enumerate(tickers):
        print(f"  [{i+1:3d}/{len(tickers)}] {ticker:<8}", end=" ", flush=True)
        sigs = _backtest_ticker(ticker, two_years_ago)
        all_signals.extend(sigs)
        wins = sum(1 for s in sigs if s["hit_target1"])
        stops = sum(1 for s in sigs if s["hit_stop"])
        print(f"→ {len(sigs):3d} sinais | {wins} wins | {stops} stops")
        time.sleep(0.25)

    return _build_report(all_signals)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Primeiros 20 tickers apenas")
    parser.add_argument("--ticker", metavar="T", help="Ticker único")
    args = parser.parse_args()

    if args.ticker:
        run_backtest([args.ticker.upper()])
    elif args.quick:
        run_backtest(ALL_TICKERS[:20])
    else:
        run_backtest()
