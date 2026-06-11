# -*- coding: utf-8 -*-
"""
Massare — ensemble REGIME-CONDICIONAL (experimento p/ atacar o edge OOS negativo).

Hipótese (López de Prado; literatura de regime-switching): cada sub-estratégia tem skill em regimes
DIFERENTES — momentum/tendência rendem em mercado em alta sustentada (bull); reversão à média/RSI rendem
em mercado lateral/baixa (bear). O ensemble atual (`engine.walk_forward`) pondera cada sub pelo acerto
recente GLOBAL, misturando regimes — o que pode anular o skill condicional.

Aqui o peso de cada sub é o acerto recente DELA DENTRO DO REGIME ATUAL (histórico separado por regime).
Tudo walk-forward/lag-safe/OOS, igual ao baseline — para comparação honesta de edge (não é promessa de
lucro; se não bater o baseline, é registrado como tal). Aditivo: NÃO altera `engine.walk_forward`.
"""
from __future__ import annotations

import math

from massare import engine


def _regime_label(row) -> str:
    """Regime barato e lag-safe: tendência pela SMA200. 'bull' (acima), 'bear' (abaixo), 'neutro' (sem dado)."""
    c = row.get("close")
    s200 = row.get("sma200")
    if c is None or s200 is None or (isinstance(s200, float) and math.isnan(s200)):
        return "neutro"
    return "bull" if c > s200 else "bear"


def walk_forward_regime(symbol, horizon=5, warmup=260, lookback=126,
                        sentiment_series="sentiment_crypto_fng") -> dict:
    """Ensemble adaptativo com pesos condicionados ao REGIME atual. Mesmas métricas OOS do baseline."""
    df = engine.load_prices(symbol)
    if len(df) < warmup + horizon + 10:
        return {"symbol": symbol, "erro": "dados insuficientes"}
    sent = engine.load_macro(sentiment_series) if sentiment_series else None
    feats = engine.make_features(df, sent)
    closes = df["close"].values
    n = len(df)

    regs = ("bull", "bear", "neutro")
    hist = {(k, r): [] for k in engine.SUBS for r in regs}   # acerto por (sub, regime)
    ens_correct, ens_total, actual_up = 0, 0, 0

    for t in range(warmup, n - horizon):
        row = feats.iloc[t]
        reg = _regime_label(row)
        fut_ret = closes[t + horizon] / closes[t] - 1.0
        actual = 1 if fut_ret >= 0 else -1
        if actual == 1:
            actual_up += 1

        votes, weights = {}, {}
        for k, fn in engine.SUBS.items():
            v = fn(row)
            votes[k] = v
            recent = hist[(k, reg)][-lookback:]
            hr = (sum(recent) / len(recent)) if recent else 0.5
            weights[k] = max(0.0, hr - 0.5)   # só vota quem bate o acaso NAQUELE regime

        score = sum(weights[k] * votes[k] for k in engine.SUBS)
        ens_dir = 1 if score > 0 else (-1 if score < 0 else engine.sig_trend(row) or 1)
        if ens_dir != 0:
            ens_correct += 1 if ens_dir == actual else 0
            ens_total += 1

        for k in engine.SUBS:
            if votes[k] != 0:
                hist[(k, reg)].append(1 if votes[k] == actual else 0)

    def hr(c, tot):
        return round(c / tot, 4) if tot else None
    n_eval = n - horizon - warmup
    base_up = hr(actual_up, n_eval)
    base_naive = round(max(base_up, 1 - base_up), 4) if base_up is not None else None
    ehr = hr(ens_correct, ens_total)
    edge = round(ehr - base_naive, 4) if (ehr is not None and base_naive is not None) else None
    return {"symbol": symbol, "horizon": horizon, "ensemble_hit_rate": ehr,
            "base_naive_rate": base_naive, "edge": edge, "ensemble_n": ens_total}


if __name__ == "__main__":
    import json
    import sys
    for s in sys.argv[1:] or ["^GSPC", "^BVSP", "BTC-USD"]:
        print(json.dumps(walk_forward_regime(s), ensure_ascii=False))
