"""
JFN Extended Backtest v2 — 2000 sessões B3 | 62 tickers IBOVESPA
==================================================================
Dados: Monte Carlo GBM com regime switching calibrado em B3/IBOVESPA
  Bull:     drift +20%aa  vol 22%aa  (duração 4–16 meses)
  Bear:     drift -18%aa  vol 35%aa  (duração 1.5–6 meses)
  Sideways: drift  +3%aa  vol 16%aa  (duração 2–8 meses)
  Fat tails: 5% chance de choque 2.5×vol | momentum AR(1)=0.07

Análise:
  - Testa limiares 45–75 (sweep completo)
  - Baseline aleatório: entradas randômicas para comparação justa
  - Cooldown 20 dias (como em produção)
  - Fundamentals realistas por ticker (distribuição normal truncada)
  - Volume intra-dia simulado com spikes ocasionais
  - Identifica indicadores mais preditivos e pesos ótimos

Run: python run_backtest_2000.py
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import talib

# ------------------------------------------------------------------ config
N_TICKERS   = 62
N_DAYS      = 2250    # 2000 avaliação + 250 warmup EMA200
N_SESSIONS  = 2000
EVAL_DAYS   = 20      # janela forward para avaliar outcome
COOLDOWN    = 20      # dias de cooldown entre sinais no mesmo ticker
TARGET1     = 0.08
TARGET2     = 0.15
STOP        = -0.04
RESULTS_FILE = Path(__file__).parent / "backtest_2000_results.json"

# Rótulos dos tickers IBOVESPA (usados só para exibição)
IBOV_NAMES = [
    "ABEV3","AZUL4","B3SA3","BBAS3","BBDC3","BBDC4","BBSE3","BEEF3",
    "BPAC11","BRFS3","CCRO3","CMIG4","CMIN3","COGN3","CPFE3","CPLE6",
    "CSAN3","CSNA3","DXCO3","EGIE3","EMBR3","ENEV3","ENBR3","EQTL3",
    "GGBR4","GOAU4","GOLL4","HAPV3","HYPE3","IGTI11","ITSA4","ITUB4",
    "JBSS3","KLBN11","LREN3","MGLU3","MRVE3","MULT3","NTCO3","PCAR3",
    "PETR3","PETR4","PRIO3","RADL3","RAIL3","RDOR3","RENT3","SAPR11",
    "SBSP3","SLCE3","SMTO3","SOMA3","SUZB3","TAEE11","TIMS3","TOTS3",
    "UGPA3","USIM5","VALE3","VIVT3","WEGE3","YDUQ3",
]

# ------------------------------------------------------------------ price simulation

REGIMES = {
    "bull":     {"mu": 0.00079, "sigma": 0.01385},  # +20%aa, 22%aa vol
    "bear":     {"mu":-0.00072, "sigma": 0.02205},  # -18%aa, 35%aa vol
    "sideways": {"mu": 0.00012, "sigma": 0.01010},  # +3%aa,  16%aa vol
}
# Transition probability matrix per regime (self-loops dominant → sticky regimes)
TRANS = {
    "bull":     {"bull": 0.9930, "bear": 0.0035, "sideways": 0.0035},
    "bear":     {"bear": 0.9870, "bull": 0.0065, "sideways": 0.0065},
    "sideways": {"sideways": 0.9900, "bull": 0.0060, "bear": 0.0040},
}


def sim_prices(n: int, seed: int, start: float = 50.0,
               vol_mult: float = 1.0) -> np.ndarray:
    """
    GBM with Markov regime switching + fat tails + AR(1) momentum.
    vol_mult lets different tickers have different base volatility.
    """
    rng = np.random.default_rng(seed)
    prices = np.empty(n)
    prices[0] = start
    regime = "bull"
    prev_ret = 0.0

    for i in range(1, n):
        # Markov regime switch
        r_keys = list(TRANS[regime].keys())
        r_probs = list(TRANS[regime].values())
        regime = rng.choice(r_keys, p=r_probs)

        p = REGIMES[regime]
        shock = 2.5 if rng.random() < 0.05 else 1.0
        eps = rng.normal(0, p["sigma"] * shock * vol_mult)
        ret = p["mu"] + 0.07 * prev_ret + eps
        prices[i] = prices[i - 1] * np.exp(ret)
        prev_ret = ret

    return prices


def sim_volume(n: int, seed: int) -> np.ndarray:
    """Log-normal volume with occasional 2–5× spikes (4% probability)."""
    rng = np.random.default_rng(seed ^ 0xDEAD)
    base = np.exp(rng.normal(13.5, 0.6, n))
    spikes = np.where(rng.random(n) < 0.04, rng.uniform(2, 5, n), 1.0)
    return base * spikes


# ------------------------------------------------------------------ indicators (talib)

def build_indicators(close: np.ndarray, volume: np.ndarray) -> dict[str, np.ndarray]:
    rsi         = talib.RSI(close, timeperiod=14)
    macd, msig, _ = talib.MACD(close, 12, 26, 9)
    _, bb_mid, bb_lo = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
    ema9        = talib.EMA(close, timeperiod=9)
    ema21       = talib.EMA(close, timeperiod=21)
    ema50       = talib.EMA(close, timeperiod=50)
    ema200      = talib.EMA(close, timeperiod=200)
    vol_sma20   = talib.SMA(volume.astype(float), timeperiod=20)
    vol_ratio   = np.where(vol_sma20 > 0, volume / vol_sma20, 1.0)

    # MACD bullish cross (lagged comparison to avoid look-ahead)
    macd_cross = (
        (np.roll(macd, 1) < np.roll(msig, 1)) & (macd >= msig)
    ).astype(float)
    macd_cross[0] = 0

    return dict(rsi=rsi, macd=macd, macd_sig=msig, macd_cross=macd_cross,
                bb_mid=bb_mid, bb_lo=bb_lo,
                ema9=ema9, ema21=ema21, ema50=ema50, ema200=ema200,
                vol_ratio=vol_ratio)


# ------------------------------------------------------------------ scoring

def score_bar(ind: dict, i: int, close: np.ndarray) -> tuple[float, dict]:
    """
    Returns (tech_score 0-100, flags_dict).
    Each of 5 indicators contributes 0-20 points.
    """
    rsi = float(ind["rsi"][i])
    rsi_sc = 20 if rsi < 30 else (15 if rsi < 40 else (5 if rsi < 50 else 0))

    mc     = bool(ind["macd_cross"][i])
    mb     = bool(ind["macd"][i] >= ind["macd_sig"][i])
    macd_sc = 20 if mc else (10 if mb else 0)

    px     = float(close[i])
    bt     = px <= float(ind["bb_lo"][i]) * 1.015
    bm     = px <= float(ind["bb_mid"][i])
    bb_sc  = 20 if bt else (10 if bm else 0)

    el     = bool(ind["ema50"][i] > ind["ema200"][i])
    es     = bool(ind["ema9"][i]  > ind["ema21"][i])
    ema_sc = 20 if (el and es) else (10 if el else (5 if es else 0))

    vr     = float(ind["vol_ratio"][i])
    vol_sc = 20 if vr >= 2.5 else (12 if vr >= 1.5 else (5 if vr >= 1.0 else 0))

    tech = float(rsi_sc + macd_sc + bb_sc + ema_sc + vol_sc)

    flags = dict(
        rsi=round(rsi, 1), rsi_oversold=(rsi < 40),
        macd_cross=mc, macd_bull=mb,
        bb_touch=bt, ema_uptrend_long=el, ema_uptrend_short=es,
        vol_ratio=round(vr, 2),
        rsi_sc=rsi_sc, macd_sc=macd_sc, bb_sc=bb_sc, ema_sc=ema_sc, vol_sc=vol_sc,
    )
    return tech, flags


def combined_score(tech: float, fund: float, sent: float) -> float:
    """Blended 0-100 score (same formula as live agent)."""
    return tech * 0.50 + fund * 0.35 + sent * 0.15


# ------------------------------------------------------------------ forward evaluation

def eval_forward(closes: np.ndarray, entry_i: int) -> dict | None:
    n = len(closes)
    if entry_i + EVAL_DAYS >= n:
        return None

    entry = float(closes[entry_i])
    t1 = entry * (1 + TARGET1)
    t2 = entry * (1 + TARGET2)
    st = entry * (1 + STOP)

    ht1 = ht2 = hst = False
    outcome = "expired"
    oday = None
    r5 = r10 = r20 = None

    for d in range(1, EVAL_DAYS + 1):
        px = float(closes[entry_i + d])
        ret = (px - entry) / entry
        if outcome == "expired":
            if px <= st:          hst = True;       outcome = "stop";   oday = d
            elif px >= t2:        ht1 = ht2 = True; outcome = "win_t2"; oday = d
            elif px >= t1:        ht1 = True;        outcome = "win_t1"; oday = d
        if d == 5:  r5  = round(ret, 4)
        if d == 10: r10 = round(ret, 4)
        if d == 20: r20 = round(ret, 4)

    return dict(hit_target1=ht1, hit_target2=ht2, hit_stop=hst,
                outcome=outcome, days_to_outcome=oday,
                return_5d=r5, return_10d=r10, return_20d=r20)


# ------------------------------------------------------------------ per-ticker backtest

def backtest_ticker(
    name: str, seed: int,
    fund_score: float = 55.0,
    vol_mult: float = 1.0,
) -> dict:
    """Run full backtest for one simulated ticker. Returns signals + random baseline."""
    start = float(np.random.default_rng(seed).uniform(15, 150))
    closes  = sim_prices(N_DAYS, seed, start, vol_mult)
    volumes = sim_volume(N_DAYS, seed)
    ind     = build_indicators(closes, volumes)

    warmup     = 210
    eval_start = max(warmup, N_DAYS - N_SESSIONS)
    eval_end   = N_DAYS - EVAL_DAYS - 1

    # Sentiment: slowly varying random walk around 55
    rng = np.random.default_rng(seed ^ 0xABCD)
    sent_walk = np.clip(55 + np.cumsum(rng.normal(0, 1, N_DAYS)), 30, 80)

    signals: list[dict] = []
    last_i = -9999

    # ---------- Signal scan ----------
    for i in range(eval_start, eval_end):
        if any(np.isnan(ind[k][i]) for k in ind):
            continue
        if i - last_i < COOLDOWN:
            continue

        tech, flags = score_bar(ind, i, closes)
        sent = float(sent_walk[i])
        combo = combined_score(tech, fund_score, sent)

        fwd = eval_forward(closes, i + 1)
        if fwd is None:
            continue

        sig = dict(ticker=name, bar_idx=i,
                   tech_score=round(tech, 1),
                   combined_score=round(combo, 1),
                   fund_score=round(fund_score, 1),
                   sent_score=round(sent, 1))
        sig.update(flags)
        sig.update(fwd)
        signals.append(sig)
        last_i = i

    # ---------- Random baseline (300 random entries per ticker) ----------
    rng2 = np.random.default_rng(seed ^ 0xF00D)
    valid_range = np.arange(eval_start, eval_end)
    n_rand = min(300, len(valid_range))
    rand_idxs = rng2.choice(valid_range, size=n_rand, replace=False)

    rand_outcomes: list[dict] = []
    for ri in rand_idxs:
        fwd = eval_forward(closes, int(ri))
        if fwd is not None:
            rand_outcomes.append(fwd)

    return dict(signals=signals, random_outcomes=rand_outcomes)


# ------------------------------------------------------------------ statistics

def build_stats(
    all_signals: list[dict],
    rand_outcomes: list[dict],
) -> dict:
    total = len(all_signals)
    if total == 0:
        return {"error": "no signals generated"}

    wt1  = sum(1 for s in all_signals if s["hit_target1"])
    wt2  = sum(1 for s in all_signals if s["hit_target2"])
    hst  = sum(1 for s in all_signals if s["hit_stop"])
    exp_ = sum(1 for s in all_signals if s["outcome"] == "expired")

    r5  = [s["return_5d"]  for s in all_signals if s["return_5d"]  is not None]
    r10 = [s["return_10d"] for s in all_signals if s["return_10d"] is not None]
    r20 = [s["return_20d"] for s in all_signals if s["return_20d"] is not None]
    ev  = float(np.mean(r20)) if r20 else 0.0

    # Random baseline
    rand_wt1 = sum(1 for s in rand_outcomes if s["hit_target1"])
    rand_ev  = float(np.mean([s["return_20d"] for s in rand_outcomes
                               if s["return_20d"] is not None])) if rand_outcomes else 0.0
    rand_wr  = rand_wt1 / max(len(rand_outcomes), 1)

    base_wr  = wt1 / total

    # Threshold sweep (technical score)
    th_sweep: dict = {}
    for th in range(40, 91, 5):
        filt = [s for s in all_signals if s["tech_score"] >= th]
        if len(filt) < 20:
            break
        wr_ = sum(1 for s in filt if s["hit_target1"]) / len(filt)
        ev_ = float(np.mean([s["return_20d"] for s in filt
                              if s["return_20d"] is not None])) if filt else 0
        th_sweep[str(th)] = dict(n=len(filt), win_rate=round(wr_, 3),
                                  avg_r20=round(ev_, 4),
                                  lift_vs_random=round(wr_ - rand_wr, 3))

    # Combined score sweep
    co_sweep: dict = {}
    for th in range(40, 86, 5):
        filt = [s for s in all_signals if s["combined_score"] >= th]
        if len(filt) < 20:
            break
        wr_ = sum(1 for s in filt if s["hit_target1"]) / len(filt)
        ev_ = float(np.mean([s["return_20d"] for s in filt
                              if s["return_20d"] is not None])) if filt else 0
        co_sweep[str(th)] = dict(n=len(filt), win_rate=round(wr_, 3),
                                  avg_r20=round(ev_, 4),
                                  lift_vs_random=round(wr_ - rand_wr, 3))

    # Per-indicator lift
    ind_keys = ["rsi_oversold","macd_cross","macd_bull","bb_touch",
                "ema_uptrend_long","ema_uptrend_short"]
    ind_stats: dict = {}
    for k in ind_keys:
        on  = [s for s in all_signals if s.get(k)]
        wr_ = sum(1 for s in on if s["hit_target1"]) / max(len(on), 1)
        ev_ = float(np.mean([s["return_20d"] for s in on
                              if s["return_20d"] is not None])) if on else 0
        ind_stats[k] = dict(n=len(on),
                             win_rate=round(wr_, 3),
                             lift_vs_random=round(wr_ - rand_wr, 3),
                             avg_r20=round(ev_, 4))

    # Score band analysis
    bands: dict = {}
    for lo, hi in [(40,50),(50,55),(55,60),(60,65),(65,70),(70,80),(80,100)]:
        bsigs = [s for s in all_signals if lo <= s["tech_score"] < hi]
        if not bsigs:
            continue
        wr_ = sum(1 for s in bsigs if s["hit_target1"]) / len(bsigs)
        ev_ = float(np.mean([s["return_20d"] for s in bsigs
                              if s["return_20d"] is not None])) if bsigs else 0
        bands[f"{lo}-{hi}"] = dict(n=len(bsigs), win_rate=round(wr_, 3),
                                    avg_r20=round(ev_, 4))

    # Find optimal threshold (best risk-adjusted: win_rate - random baseline)
    best_th_wr  = max(th_sweep, key=lambda k: th_sweep[k]["win_rate"]) if th_sweep else "65"
    best_th_ev  = max(th_sweep, key=lambda k: th_sweep[k]["avg_r20"]) if th_sweep else "65"
    best_th_lift = max(th_sweep, key=lambda k: th_sweep[k]["lift_vs_random"]) if th_sweep else "65"

    return dict(
        total_signals=total,
        win_rate_t1=round(base_wr, 3),
        win_rate_t2=round(wt2/total, 3),
        stop_rate=round(hst/total, 3),
        expired_rate=round(exp_/total, 3),
        avg_return_5d=round(float(np.mean(r5)), 4)   if r5  else None,
        avg_return_10d=round(float(np.mean(r10)), 4) if r10 else None,
        avg_return_20d=round(float(np.mean(r20)), 4) if r20 else None,
        expectancy_20d=round(ev, 4),
        # Random baseline comparison
        random_n=len(rand_outcomes),
        random_win_rate=round(rand_wr, 3),
        random_ev_20d=round(rand_ev, 4),
        signal_lift_vs_random=round(base_wr - rand_wr, 3),
        signal_ev_lift=round(ev - rand_ev, 4),
        # Analysis tables
        tech_threshold_sweep=th_sweep,
        combined_threshold_sweep=co_sweep,
        indicator_stats=ind_stats,
        score_band_analysis=bands,
        optimal_tech_threshold_winrate=best_th_wr,
        optimal_tech_threshold_ev=best_th_ev,
        optimal_tech_threshold_lift=best_th_lift,
        signals_per_ticker=round(total / N_TICKERS, 1),
    )


# ------------------------------------------------------------------ main

def run():
    print(f"\n{'='*66}")
    print(f"  JFN Backtest v2 — Monte Carlo B3")
    print(f"  {N_TICKERS} tickers IBOVESPA  |  {N_SESSIONS} sessões/ticker  |  {N_TICKERS * N_SESSIONS:,} bar-days")
    print(f"  T1=+{TARGET1:.0%}  T2=+{TARGET2:.0%}  Stop={STOP:.0%}  Cooldown={COOLDOWN}d")
    print(f"  Regime switching calibrado em parâmetros históricos B3")
    print(f"{'='*66}\n")

    rng_main = np.random.default_rng(2024)

    all_signals:  list[dict] = []
    rand_all:     list[dict] = []

    for i, name in enumerate(IBOV_NAMES):
        seed = i * 137 + 42
        # Realistic fund_score distribution: mean=65 std=14 min=30 max=92
        # (higher for utility/perennial names, lower for volatile/leveraged ones)
        fund_sc = float(np.clip(rng_main.normal(65, 14), 30, 92))
        # Volatility multiplier: 0.7 (utilities) to 1.5 (commodities/growth)
        vol_m = float(np.clip(rng_main.normal(1.0, 0.20), 0.65, 1.55))

        result = backtest_ticker(name, seed, fund_sc, vol_m)
        sigs  = result["signals"]
        rands = result["random_outcomes"]

        all_signals.extend(sigs)
        rand_all.extend(rands)

        wt = sum(1 for s in sigs if s["hit_target1"])
        st = sum(1 for s in sigs if s["hit_stop"])
        wr = f"{wt/max(len(sigs),1)*100:.0f}%" if sigs else "  -"
        print(f"  {name:<10}  fund={fund_sc:.0f}  vol={vol_m:.2f}x"
              f"  |  {len(sigs):3d} sinais  {wt:3d} wins ({wr})  {st:3d} stops")

    print(f"\n  Total: {len(all_signals)} sinais  |  {len(rand_all)} entradas aleatórias\n")

    s = build_stats(all_signals, rand_all)

    report = dict(
        meta=dict(run_date=datetime.now().isoformat(),
                  n_tickers=N_TICKERS, n_sessions=N_SESSIONS,
                  n_bar_days=N_TICKERS * N_SESSIONS,
                  target1=TARGET1, target2=TARGET2, stop=STOP,
                  cooldown=COOLDOWN),
        stats=s, signals=all_signals,
    )
    with open(RESULTS_FILE, "w") as f:
        json.dump(report, f, indent=2)

    # ---- Print detailed report ----
    print(f"\n{'='*66}")
    print(f"  RESULTADO — {s['total_signals']:,} sinais gerados")
    print(f"{'='*66}")
    print(f"  Win rate T1 (+8%)   : {s['win_rate_t1']*100:.1f}%")
    print(f"  Win rate T2 (+15%)  : {s['win_rate_t2']*100:.1f}%")
    print(f"  Stop rate  (-4%)    : {s['stop_rate']*100:.1f}%")
    print(f"  Expirado (20d)      : {s['expired_rate']*100:.1f}%")
    print(f"  Retorno médio  5d   : {(s['avg_return_5d']  or 0)*100:+.2f}%")
    print(f"  Retorno médio 10d   : {(s['avg_return_10d'] or 0)*100:+.2f}%")
    print(f"  Retorno médio 20d   : {(s['avg_return_20d'] or 0)*100:+.2f}%")
    print(f"  Expectancy 20d      : {s['expectancy_20d']*100:+.2f}%")

    print(f"\n  ─── COMPARAÇÃO COM BASELINE ALEATÓRIO ───")
    print(f"  Random win rate     : {s['random_win_rate']*100:.1f}%   ({s['random_n']:,} entradas)")
    print(f"  Random expectancy   : {s['random_ev_20d']*100:+.2f}%")
    print(f"  Lift win rate       : {s['signal_lift_vs_random']*100:+.1f}pp vs aleatório")
    print(f"  Lift expectância    : {s['signal_ev_lift']*100:+.2f}pp vs aleatório")

    print(f"\n  ─── ANÁLISE POR FAIXA DE SCORE TÉCNICO ───")
    for band, bv in s.get("score_band_analysis", {}).items():
        bar = "█" * min(25, int(bv["win_rate"] * 40))
        print(f"  Tech {band:7s}: n={bv['n']:5d}  WR={bv['win_rate']*100:.1f}%  EV={bv['avg_r20']*100:+.2f}%  {bar}")

    print(f"\n  ─── SWEEP DE LIMIAR TÉCNICO ───")
    for th, tv in s.get("tech_threshold_sweep", {}).items():
        bar = "█" * min(25, int(tv["win_rate"] * 40))
        lift_sign = "+" if tv["lift_vs_random"] >= 0 else ""
        print(f"  th={th}  n={tv['n']:5d}  WR={tv['win_rate']*100:.1f}%"
              f"  EV={tv['avg_r20']*100:+.2f}%"
              f"  lift={lift_sign}{tv['lift_vs_random']*100:.1f}pp  {bar}")
    print(f"  → Ótimo win rate   : tech >= {s['optimal_tech_threshold_winrate']}")
    print(f"  → Ótimo expectância: tech >= {s['optimal_tech_threshold_ev']}")
    print(f"  → Ótimo lift       : tech >= {s['optimal_tech_threshold_lift']}")

    print(f"\n  ─── LIFT POR INDICADOR ───  (baseline aleatório: {s['random_win_rate']*100:.1f}%)")
    for k, v in sorted(s.get("indicator_stats", {}).items(),
                        key=lambda x: -x[1]["lift_vs_random"]):
        sign = "+" if v["lift_vs_random"] >= 0 else ""
        bar = "█" * min(25, max(0, int(abs(v["lift_vs_random"]) * 200)))
        print(f"  {k:<25}: n={v['n']:5d}  WR={v['win_rate']*100:.1f}%"
              f"  lift={sign}{v['lift_vs_random']*100:.1f}pp  {bar}")

    print(f"\n  Salvo em: {RESULTS_FILE.name}")
    print(f"{'='*66}\n")

    return s


if __name__ == "__main__":
    run()
