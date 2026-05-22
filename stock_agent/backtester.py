"""
JFN Backtester — 2-year historical simulation of the signal algorithm.

Uses pure pandas/numpy for all indicators (no external TA library).
Matches the exact scoring logic of analyzer.py.

Strategy:
- Entry price: close of the day *after* the signal (conservative)
- Targets: +8% (T1) and +15% (T2) | Stop loss: -4%
- Evaluation window: up to 20 trading days forward
- Cooldown: 20 trading days after a signal on the same ticker

Usage:
    python backtester.py                  # full IBOV+SMLL run
    python backtester.py --quick          # first 20 tickers only
    python backtester.py --ticker WEGE3   # single ticker
"""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from config import IBOVESPA_TICKERS, SIGNAL_THRESHOLD, SMLL_TICKERS

ALL_TICKERS = list(dict.fromkeys(IBOVESPA_TICKERS + SMLL_TICKERS))
RESULTS_FILE = Path(__file__).parent / "backtest_results.json"

TARGET1 = 0.08
TARGET2 = 0.15
STOP = -0.04
EVAL_DAYS = 20
COOLDOWN_DAYS = 20


# ---------------------------------------------------------------------------
# Pure-pandas indicators (same formulas as analyzer.py)
# ---------------------------------------------------------------------------

def _rsi_series(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)
    avg_gain = gains.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd_series(close: pd.Series, fast=12, slow=26, sig=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=sig, adjust=False).mean()
    cross = ((macd.shift(1) < signal.shift(1)) & (macd >= signal)).astype(float)
    return macd, signal, cross


def _bb_lower_series(close: pd.Series, window=20, n_std=2.0):
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    return (mid - n_std * std), mid


def _ema_series(close: pd.Series, window: int) -> pd.Series:
    return close.ewm(span=window, adjust=False).mean()


def _build_indicator_df(df: pd.DataFrame) -> pd.DataFrame:
    """Pre-compute all indicators for every row in one pass."""
    close = df["Close"].squeeze()
    volume = df["Volume"].squeeze()

    out = pd.DataFrame(index=df.index)
    out["close"] = close.values
    out["volume"] = volume.values

    out["rsi"] = _rsi_series(close).values

    macd, msig, cross = _macd_series(close)
    out["macd"] = macd.values
    out["macd_sig"] = msig.values
    out["macd_cross"] = cross.values
    out["macd_bull"] = (macd >= msig).astype(float).values

    bb_lo, bb_mid = _bb_lower_series(close)
    out["bb_lo"] = bb_lo.values
    out["bb_mid"] = bb_mid.values

    out["ema9"]   = _ema_series(close, 9).values
    out["ema21"]  = _ema_series(close, 21).values
    out["ema50"]  = _ema_series(close, 50).values
    out["ema200"] = _ema_series(close, 200).values

    vol_avg = volume.rolling(20).mean()
    out["vol_ratio"] = (volume / vol_avg.replace(0, np.nan)).clip(upper=10).values

    return out.dropna()


# ---------------------------------------------------------------------------
# Scoring (mirrors analyzer.py exactly)
# ---------------------------------------------------------------------------

def _score_row(row: pd.Series) -> float:
    """Score a single pre-computed indicator row. Max = 100."""
    rsi = float(row["rsi"])
    rsi_sc = 22 if rsi < 30 else (16 if rsi < 40 else (5 if rsi < 50 else 0))

    mc = bool(row["macd_cross"])
    mb = bool(row["macd_bull"])
    macd_sc = 28 if mc else (6 if mb else 0)

    px = float(row["close"])
    bt = px <= float(row["bb_lo"]) * 1.015
    bm = px <= float(row["bb_mid"])
    bb_sc = 20 if bt else (8 if bm else 0)

    el = bool(row["ema50"] > row["ema200"])
    es = bool(row["ema9"] > row["ema21"])
    ema_sc = 22 if (el and not es) else (20 if (el and es) else 0)

    vr = float(row["vol_ratio"])
    vol_sc = 8 if vr >= 2.0 else (4 if vr >= 1.5 else (1 if vr >= 1.0 else 0))

    return float(rsi_sc + macd_sc + bb_sc + ema_sc + vol_sc)


def _combined(tech: float, fund_proxy: float = 55.0) -> float:
    return tech * 0.50 + fund_proxy * 0.35 + 60.0 * 0.15


# ---------------------------------------------------------------------------
# Forward outcome evaluation
# ---------------------------------------------------------------------------

def _evaluate_forward(closes: np.ndarray, entry_idx: int) -> dict:
    n = len(closes)
    if entry_idx >= n:
        return {}

    entry = float(closes[entry_idx])
    t1 = entry * (1 + TARGET1)
    t2 = entry * (1 + TARGET2)
    st = entry * (1 + STOP)

    res = dict(entry_price=round(entry, 2),
               hit_target1=False, hit_target2=False, hit_stop=False,
               outcome="expired", days_to_outcome=None,
               return_5d=None, return_10d=None, return_20d=None)

    outcome_set = False
    for d in range(1, min(EVAL_DAYS + 1, n - entry_idx)):
        px = float(closes[entry_idx + d])
        ret = (px - entry) / entry
        if not outcome_set:
            if px <= st:
                res.update(hit_stop=True, outcome="stop", days_to_outcome=d)
                outcome_set = True
            elif px >= t2:
                res.update(hit_target1=True, hit_target2=True,
                           outcome="win_t2", days_to_outcome=d)
                outcome_set = True
            elif px >= t1:
                res.update(hit_target1=True, outcome="win_t1",
                           days_to_outcome=d)
                outcome_set = True
        if d == 5:  res["return_5d"]  = round(ret, 4)
        if d == 10: res["return_10d"] = round(ret, 4)
        if d == 20: res["return_20d"] = round(ret, 4)

    return res


# ---------------------------------------------------------------------------
# Per-ticker backtest
# ---------------------------------------------------------------------------

def _backtest_ticker(ticker: str, two_years_ago: pd.Timestamp) -> list[dict]:
    try:
        df = yf.download(f"{ticker}.SA", period="3y", interval="1d",
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        if df.empty or len(df) < 220:
            return []
    except Exception:
        return []

    ind = _build_indicator_df(df)
    if ind.empty:
        return []

    tz = ind.index.tz
    cutoff = two_years_ago.tz_localize(tz) if tz and two_years_ago.tzinfo is None else two_years_ago
    eval_rows = ind[ind.index >= cutoff].iloc[:-21]
    if eval_rows.empty:
        return []

    closes = ind["close"].values
    all_idx = ind.index

    signals = []
    last_signal_row = -999

    for date, row in eval_rows.iterrows():
        abs_i = all_idx.get_loc(date)
        if abs_i - last_signal_row < COOLDOWN_DAYS:
            continue

        tech = _score_row(row)
        combined = _combined(tech)

        if combined < SIGNAL_THRESHOLD:
            continue

        entry_abs = abs_i + 1
        if entry_abs >= len(closes):
            continue

        outcome = _evaluate_forward(closes, entry_abs)
        if not outcome:
            continue

        signals.append(dict(
            ticker=ticker,
            signal_date=str(date.date()),
            tech_score=round(tech, 1),
            combined_score=round(combined, 1),
            rsi=round(float(row["rsi"]), 1),
            rsi_oversold=float(row["rsi"]) < 40,
            macd_cross=bool(row["macd_cross"]),
            macd_bull=bool(row["macd_bull"]),
            bb_touch=float(row["close"]) <= float(row["bb_lo"]) * 1.015,
            ema_uptrend_long=bool(row["ema50"] > row["ema200"]),
            ema_uptrend_short=bool(row["ema9"] > row["ema21"]),
            vol_ratio=round(float(row["vol_ratio"]), 2),
            **outcome,
        ))
        last_signal_row = abs_i

    return signals


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------

def _build_report(all_signals: list[dict]) -> dict:
    total = len(all_signals)
    if total == 0:
        report = {"meta": {"total_signals": 0,
                           "run_date": datetime.now().isoformat()}, "signals": []}
        with open(RESULTS_FILE, "w") as f:
            json.dump(report, f, indent=2)
        return report

    wt1 = sum(1 for s in all_signals if s["hit_target1"])
    wt2 = sum(1 for s in all_signals if s["hit_target2"])
    hst = sum(1 for s in all_signals if s["hit_stop"])
    r10 = [s["return_10d"] for s in all_signals if s["return_10d"] is not None]
    r20 = [s["return_20d"] for s in all_signals if s["return_20d"] is not None]

    ticker_stats: dict = {}
    for s in all_signals:
        t = s["ticker"]
        if t not in ticker_stats:
            ticker_stats[t] = {"total": 0, "wins": 0}
        ticker_stats[t]["total"] += 1
        if s["hit_target1"]:
            ticker_stats[t]["wins"] += 1

    best = max(ticker_stats,
               key=lambda t: ticker_stats[t]["wins"] / max(ticker_stats[t]["total"], 1))

    meta = dict(
        run_date=datetime.now().isoformat(),
        total_signals=total,
        win_rate_t1=round(wt1 / total, 3),
        win_rate_t2=round(wt2 / total, 3),
        stop_rate=round(hst / total, 3),
        avg_return_10d=round(float(np.mean(r10)), 4) if r10 else None,
        avg_return_20d=round(float(np.mean(r20)), 4) if r20 else None,
        best_ticker=best,
        ticker_stats=ticker_stats,
    )

    report = {"meta": meta, "signals": all_signals}
    with open(RESULTS_FILE, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{'='*55}")
    print(f"  BACKTEST — {total} sinais | 2 anos")
    print(f"  Win rate T1 (+8%):  {meta['win_rate_t1']*100:.1f}%")
    print(f"  Win rate T2 (+15%): {meta['win_rate_t2']*100:.1f}%")
    print(f"  Stop rate  (-4%):   {meta['stop_rate']*100:.1f}%")
    if meta["avg_return_20d"]:
        print(f"  Retorno médio 20d:  {meta['avg_return_20d']*100:+.2f}%")
    print(f"  Melhor ticker:      {best}")
    print(f"  Salvo em:           backtest_results.json")
    print(f"{'='*55}\n")
    return report


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_backtest(tickers: list[str] | None = None) -> dict:
    tickers = tickers or ALL_TICKERS
    two_years_ago = pd.Timestamp.now() - pd.DateOffset(years=2)

    print(f"\n{'='*55}")
    print(f"  JFN Backtester — {len(tickers)} tickers | limiar {SIGNAL_THRESHOLD}/100")
    print(f"  Período: {two_years_ago.strftime('%d/%m/%Y')} → hoje")
    print(f"{'='*55}\n")

    all_signals: list[dict] = []
    for i, ticker in enumerate(tickers):
        print(f"  [{i+1:3d}/{len(tickers)}] {ticker:<10}", end=" ", flush=True)
        sigs = _backtest_ticker(ticker, two_years_ago)
        all_signals.extend(sigs)
        wins  = sum(1 for s in sigs if s["hit_target1"])
        stops = sum(1 for s in sigs if s["hit_stop"])
        print(f"→ {len(sigs):3d} sinais | {wins} wins | {stops} stops")
        time.sleep(0.25)

    return _build_report(all_signals)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick",  action="store_true", help="Primeiros 20 tickers")
    parser.add_argument("--ticker", metavar="T",         help="Ticker único")
    args = parser.parse_args()

    if args.ticker:
        run_backtest([args.ticker.upper()])
    elif args.quick:
        run_backtest(ALL_TICKERS[:20])
    else:
        run_backtest()
