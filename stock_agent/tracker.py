"""
Live signal outcome tracker.

When the agent sends a WhatsApp alert, register_signal() records it.
check_outcomes() is called at the start of each scan to evaluate pending
signals against current market prices and resolve wins/stops/expirations.
After each resolution, learner.learn() is called to refresh weights.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytz
import yfinance as yf

import learner

LIVE_FILE = Path(__file__).parent / "live_signals.json"
BRT = pytz.timezone("America/Sao_Paulo")

TARGET1 = 0.08
TARGET2 = 0.15
STOP = -0.04
EXPIRY_DAYS = 20


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load() -> dict:
    if LIVE_FILE.exists():
        with open(LIVE_FILE) as f:
            return json.load(f)
    return {}


def _save(data: dict) -> None:
    with open(LIVE_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_signal(
    ticker: str,
    entry_price: float,
    score: float,
    tech: dict,
    fund_raw: dict,
    fund_score: float = 50.0,
    sent_score: float = 60.0,
) -> None:
    """Record a newly sent live signal for future outcome tracking."""
    signals = _load()
    today = datetime.now(BRT).date().isoformat()
    key = f"{ticker}_{today}"

    signals[key] = {
        "ticker": ticker,
        "signal_date": today,
        "entry_price": round(entry_price, 2),
        "score": round(score, 1),
        "tech_score": tech.get("technical_score", 50),
        "fund_score": round(fund_score, 1),
        "sent_score": round(sent_score, 1),
        "target1": round(entry_price * (1 + TARGET1), 2),
        "target2": round(entry_price * (1 + TARGET2), 2),
        "stop": round(entry_price * (1 + STOP), 2),
        # Raw indicator flags (used by learner)
        "rsi": tech.get("rsi"),
        "macd_cross": "CRUZAMENTO" in tech.get("macd_signal", ""),
        "macd_bull": "ALTA" in tech.get("macd_signal", ""),
        "bb_touch": "SUPORTE" in tech.get("bb_signal", ""),
        "ema_uptrend_long": any(
            kw in tech.get("trend", "") for kw in ("PRIMÁRIA", "ALTA PRIMÁRIA")
        ),
        "ema_uptrend_short": any(
            kw in tech.get("trend", "") for kw in ("CURTO", "ALTA PRIMÁRIA", "SECUNDÁRIA")
        ),
        "volume_ratio": tech.get("volume_ratio", 1.0),
        # Outcome fields (filled in by check_outcomes)
        "status": "pending",
        "resolved_date": None,
        "outcome": None,
        "hit_target1": None,
        "hit_target2": None,
        "hit_stop": None,
        "return_actual": None,
    }

    _save(signals)
    print(f"[tracker] 📌 {key} registrado para acompanhamento.")


def check_outcomes() -> int:
    """
    Evaluate all pending signals against current prices.
    Returns the number of signals resolved in this call.
    """
    signals = _load()
    pending = {k: v for k, v in signals.items() if v.get("status") == "pending"}

    if not pending:
        return 0

    resolved_count = 0

    for key, sig in pending.items():
        try:
            info = yf.Ticker(f"{sig['ticker']}.SA").fast_info
            current = float(info.last_price)
        except Exception:
            continue

        entry = sig["entry_price"]
        ret = (current - entry) / entry
        signal_date = datetime.fromisoformat(sig["signal_date"])
        days_elapsed = (datetime.now() - signal_date).days

        outcome: str | None = None
        if current >= sig["target2"]:
            outcome = "win_t2"
        elif current >= sig["target1"]:
            outcome = "win_t1"
        elif current <= sig["stop"]:
            outcome = "stop"
        elif days_elapsed >= EXPIRY_DAYS:
            outcome = "expired"

        if outcome is None:
            continue

        sig.update(
            status=outcome,
            outcome=outcome,
            resolved_date=datetime.now(BRT).date().isoformat(),
            hit_target1=current >= sig["target1"],
            hit_target2=current >= sig["target2"],
            hit_stop=current <= sig["stop"],
            return_actual=round(ret, 4),
        )
        signals[key] = sig
        resolved_count += 1

        emoji = "✅" if outcome.startswith("win") else ("🛑" if outcome == "stop" else "⏰")
        print(f"[tracker] {emoji} {sig['ticker']} → {outcome} | retorno: {ret*100:+.1f}%")

    _save(signals)

    if resolved_count > 0:
        print(f"[tracker] {resolved_count} sinal(is) resolvido(s). Atualizando pesos...")
        learner.learn(verbose=False)

    return resolved_count


def get_stats() -> dict:
    """Return a summary of all live signal outcomes."""
    signals = _load()
    if not signals:
        return {"total": 0, "pending": 0, "resolved": 0}

    pending = [v for v in signals.values() if v.get("status") == "pending"]
    resolved = [v for v in signals.values() if v.get("status") not in ("pending", None)]

    wins = [s for s in resolved if s.get("status", "").startswith("win")]
    stops = [s for s in resolved if s.get("status") == "stop"]
    returns = [s["return_actual"] for s in resolved if s.get("return_actual") is not None]

    return {
        "total": len(signals),
        "pending": len(pending),
        "resolved": len(resolved),
        "wins": len(wins),
        "stops": len(stops),
        "win_rate": round(len(wins) / len(resolved), 3) if resolved else 0.0,
        "stop_rate": round(len(stops) / len(resolved), 3) if resolved else 0.0,
        "avg_return": round(sum(returns) / len(returns), 4) if returns else 0.0,
    }
