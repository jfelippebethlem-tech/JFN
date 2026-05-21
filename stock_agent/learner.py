"""
Learns optimal indicator weights from backtest + live signal outcomes.

Algorithm:
1. Build feature matrix (one row per resolved signal)
2. Compute per-indicator "lift" = win_rate_when_fires - baseline_win_rate
3. Convert lifts to weights: blend 50% lift-proportional + 50% equal (avoids overfitting)
4. Adjust top-level weights (technical/fundamental/sentiment) by sub-score correlation
5. Save to learned_weights.json

Minimum 20 resolved signals required; falls back to equal weights otherwise.
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np

RESULTS_FILE = Path(__file__).parent / "backtest_results.json"
LIVE_FILE = Path(__file__).parent / "live_signals.json"
WEIGHTS_FILE = Path(__file__).parent / "learned_weights.json"

DEFAULTS = {
    "indicator_weights": {
        "rsi_oversold": 0.20,
        "macd_cross": 0.20,
        "bb_touch": 0.20,
        "ema_uptrend_long": 0.20,
        "vol_ratio": 0.20,
    },
    "top_level_weights": {
        "technical": 0.50,
        "fundamental": 0.35,
        "sentiment": 0.15,
    },
    "meta": {
        "n_signals": 0,
        "baseline_win_rate": None,
        "generated_at": None,
        "source": "defaults",
    },
}

FEATURE_NAMES = ["rsi_oversold", "macd_cross", "bb_touch", "ema_uptrend_long", "vol_ratio"]


def load_weights() -> dict:
    """Return learned weights; use defaults if file missing or corrupt."""
    try:
        with open(WEIGHTS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULTS.copy()


def _collect_signals() -> list[dict]:
    """Merge backtest + resolved live signals into a unified list."""
    signals: list[dict] = []

    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            data = json.load(f)
        signals.extend(data.get("signals", []))

    if LIVE_FILE.exists():
        with open(LIVE_FILE) as f:
            live = json.load(f)
        resolved_statuses = {"win_t1", "win_t2", "stop", "expired"}
        for sig in live.values():
            if sig.get("status") in resolved_statuses:
                # Normalise field names to match backtest schema
                normalized = {
                    "rsi_oversold": 1 if (sig.get("rsi") or 50) < 40 else 0,
                    "macd_cross": int(bool(sig.get("macd_cross", False))),
                    "bb_touch": int(bool(sig.get("bb_touch", False))),
                    "ema_uptrend_long": int(bool(sig.get("ema_uptrend_long", False))),
                    "vol_ratio": min(float(sig.get("volume_ratio", 1.0)), 4.0) / 4.0,
                    "hit_target1": bool(sig.get("hit_target1", False)),
                    "hit_target2": bool(sig.get("hit_target2", False)),
                    "outcome": sig.get("status", "expired"),
                    "tech_score": sig.get("tech_score", 50),
                    "fund_score": sig.get("fund_score", 50),
                    "sent_score": sig.get("sent_score", 60),
                }
                signals.append(normalized)

    return signals


def _compute_lifts(X: np.ndarray, y: np.ndarray) -> dict[str, float]:
    """
    Per-indicator lift = win_rate_when_indicator_fires - baseline_win_rate.
    Negative lifts are clamped to 0.
    """
    baseline = float(y.mean())
    lifts: dict[str, float] = {}

    for i, name in enumerate(FEATURE_NAMES):
        col = X[:, i]
        # Binarise continuous features (vol_ratio) at 0.5
        mask = col >= 0.5
        if mask.sum() >= 5 and (~mask).sum() >= 5:
            wr_on = float(y[mask].mean())
            lift = max(0.0, wr_on - baseline)
        else:
            lift = 0.0
        lifts[name] = lift

    return lifts


def _lifts_to_weights(lifts: dict[str, float]) -> dict[str, float]:
    """
    Convert lifts to normalised weights.
    Blend: 50% lift-proportional + 50% equal (dampens overfitting on small datasets).
    """
    n = len(lifts)
    total = sum(lifts.values())
    equal = 1.0 / n

    if total < 0.01:
        return {k: round(equal, 4) for k in lifts}

    weights = {
        k: round(0.5 * (v / total) + 0.5 * equal, 4)
        for k, v in lifts.items()
    }
    # Re-normalise to sum exactly to 1
    s = sum(weights.values())
    return {k: round(v / s, 4) for k, v in weights.items()}


def _adjust_top_level(signals: list[dict], baseline_wr: float) -> dict[str, float]:
    """
    Nudge top-level weights based on sub-score correlation with wins.
    Capped at ±10pp from defaults to avoid wild swings.
    """
    defaults = DEFAULTS["top_level_weights"]
    wins = [s for s in signals if s.get("hit_target1") or s.get("outcome") in ("win_t1", "win_t2")]
    losses = [s for s in signals if not (s.get("hit_target1") or s.get("outcome") in ("win_t1", "win_t2"))]

    if len(wins) < 5 or len(losses) < 5:
        return defaults.copy()

    def avg_score(group: list[dict], key: str) -> float:
        vals = [s[key] for s in group if key in s and s[key] is not None]
        return float(np.mean(vals)) if vals else 50.0

    delta_tech = avg_score(wins, "tech_score") - avg_score(losses, "tech_score")
    delta_fund = avg_score(wins, "fund_score") - avg_score(losses, "fund_score")
    delta_sent = avg_score(wins, "sent_score") - avg_score(losses, "sent_score")

    # Scale deltas: each 10-point sub-score delta -> 2pp weight adjustment
    nudge_tech = np.clip(delta_tech * 0.002, -0.10, 0.10)
    nudge_fund = np.clip(delta_fund * 0.002, -0.10, 0.10)

    tech_w = float(np.clip(defaults["technical"] + nudge_tech, 0.35, 0.65))
    fund_w = float(np.clip(defaults["fundamental"] + nudge_fund, 0.20, 0.50))
    sent_w = max(0.05, 1.0 - tech_w - fund_w)

    # Normalise
    total = tech_w + fund_w + sent_w
    return {
        "technical": round(tech_w / total, 3),
        "fundamental": round(fund_w / total, 3),
        "sentiment": round(sent_w / total, 3),
    }


def learn(verbose: bool = True) -> dict:
    """
    Analyse all resolved signals and update learned_weights.json.
    Returns the new weights dict (or defaults if insufficient data).
    """
    signals = _collect_signals()
    resolved = [
        s for s in signals
        if s.get("outcome") in ("win_t1", "win_t2", "stop", "expired")
        or s.get("hit_target1") is not None
    ]

    if verbose:
        print(f"[learner] {len(resolved)} sinais resolvidos disponíveis.")

    if len(resolved) < 20:
        if verbose:
            print("[learner] Mínimo de 20 sinais não atingido. Usando pesos padrão.")
        return DEFAULTS.copy()

    # Build feature matrix
    rows = []
    labels = []
    for s in resolved:
        rsi_ov = float(s.get("rsi_oversold", 0))
        rows.append([
            rsi_ov,
            float(s.get("macd_cross", 0)),
            float(s.get("bb_touch", 0)),
            float(s.get("ema_uptrend_long", 0)),
            min(float(s.get("vol_ratio", 0.25)), 1.0),  # already normalised 0-1
        ])
        win = s.get("hit_target1") or s.get("outcome") in ("win_t1", "win_t2")
        labels.append(1 if win else 0)

    X = np.array(rows)
    y = np.array(labels)
    baseline_wr = float(y.mean())

    lifts = _compute_lifts(X, y)
    indicator_weights = _lifts_to_weights(lifts)
    top_level = _adjust_top_level(resolved, baseline_wr)

    weights = {
        "indicator_weights": indicator_weights,
        "top_level_weights": top_level,
        "meta": {
            "n_signals": len(resolved),
            "baseline_win_rate": round(baseline_wr, 3),
            "generated_at": datetime.now().isoformat(),
            "source": "learned",
        },
    }

    with open(WEIGHTS_FILE, "w") as f:
        json.dump(weights, f, indent=2)

    if verbose:
        print(f"\n  Win rate geral  : {baseline_wr*100:.1f}%")
        print("  Pesos por indicador (lift):")
        for name, w in sorted(indicator_weights.items(), key=lambda x: -x[1]):
            lift = lifts.get(name, 0)
            print(f"    {name:<22}: {w:.0%}  (lift +{lift*100:.1f}pp)")
        print(f"\n  Pesos top-nível :")
        for k, v in top_level.items():
            print(f"    {k:<15}: {v:.0%}")
        print(f"\n  Salvo em learned_weights.json\n")

    return weights


if __name__ == "__main__":
    learn(verbose=True)
