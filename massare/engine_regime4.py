# -*- coding: utf-8 -*-
"""
Massare — ensemble REGIME-CONDICIONAL com GRADE 2×2 (4 regimes) + DRIFT-AWARE (peso recente).

Evolução honesta do `engine_regime` (que usava só 2 regimes de tendência, bull/bear via SMA200, e
ainda ficava com edge OOS negativo no universo). Duas mudanças, ambas fundamentadas e lag-safe:

1. **4 regimes = tendência × volatilidade** (grade 2×2, clássico em regime-switching de mercado):
   `{bull,bear}` (close vs SMA200) × `{calm,turb}` (vol21 vs sua MEDIANA móvel trailing). A intuição: o
   skill de momentum/reversão não depende só da direção do mercado, mas também do nível de turbulência —
   reversão à média funciona em mercado calmo, momentum sofre em turbulência, etc. Separar por 4 células
   deixa cada sub votar só onde, no passado, ELA bateu o acaso NAQUELE regime.

2. **DRIFT-AWARE:** em vez de média simples de uma janela fixa (que trata acerto de 2 anos atrás igual ao
   de ontem), o acerto de cada (sub, regime) é uma EWMA com meia-vida — performance recente pesa mais, e o
   peso encolhe quando a célula ainda tem poucas amostras (anti-ruído). Isso acompanha *concept drift*: se
   uma sub para de funcionar num regime, ela perde voz rápido; se volta, recupera. Mantém-se um piso de
   amostras (`min_amostras`) com rampa linear para não confiar em célula recém-nascida.

Tudo walk-forward / lag-safe / OOS, com as MESMAS métricas do baseline (`engine.walk_forward`) — para
comparação honesta de edge. Aditivo: NÃO altera `engine` nem `engine_regime`. Não é promessa de lucro; se
não bater o piso ingênuo, fica registrado como tal.
"""
from __future__ import annotations

import math

from massare import engine

_REGS4 = ("bull_calm", "bull_turb", "bear_calm", "bear_turb", "neutro")


def _regime4_label(close, sma200, vol21, vol_med) -> str:
    """Regime 2×2 (tendência × volatilidade), lag-safe. 'neutro' quando falta a tendência (warmup)."""
    def _nan(x):
        return x is None or (isinstance(x, float) and math.isnan(x))
    if _nan(close) or _nan(sma200):
        return "neutro"
    trend = "bull" if close > sma200 else "bear"
    # bucket de volatilidade: turbulento se vol21 acima da mediana trailing; calmo caso contrário.
    # sem dado de vol (início da série) => assume 'calm' (conservador).
    volb = "turb" if (not _nan(vol21) and not _nan(vol_med) and vol21 > vol_med) else "calm"
    return f"{trend}_{volb}"


def _alpha_from_halflife(half_life: float) -> float:
    """Converte meia-vida (em passos) no fator de decaimento EWMA alpha = 1 - 0.5**(1/half_life)."""
    half_life = max(1.0, float(half_life))
    return 1.0 - 0.5 ** (1.0 / half_life)


def walk_forward_regime4(symbol, horizon=5, warmup=260, half_life=63, min_amostras=40,
                         vol_window=252, sentiment_series="sentiment_crypto_fng",
                         drift=True) -> dict:
    """Ensemble com 4 regimes + peso drift-aware (EWMA). Mesmas métricas OOS do baseline.

    drift=True  -> peso = EWMA de acerto (meia-vida `half_life`), recência pesa mais.
    drift=False -> peso = média simples da janela (ablation, p/ isolar o ganho do drift)."""
    df = engine.load_prices(symbol)
    if len(df) < warmup + horizon + 10:
        return {"symbol": symbol, "erro": "dados insuficientes"}
    sent = engine.load_macro(sentiment_series) if sentiment_series else None
    feats = engine.make_features(df, sent)
    closes = df["close"].values
    n = len(df)

    # mediana trailing da volatilidade (lag-safe: só usa vol21 até t, tudo conhecido em t)
    vol_med = feats["vol21"].rolling(vol_window, min_periods=60).median()

    alpha = _alpha_from_halflife(half_life)
    # estado por (sub, regime): EWMA do acerto (init 0.5) + contagem de amostras
    ewma = {(k, r): 0.5 for k in engine.SUBS for r in _REGS4}
    cnt = {(k, r): 0 for k in engine.SUBS for r in _REGS4}
    flat = {(k, r): [] for k in engine.SUBS for r in _REGS4}   # p/ ablation drift=False

    ens_correct, ens_total, actual_up = 0, 0, 0

    for t in range(warmup, n - horizon):
        row = feats.iloc[t]
        reg = _regime4_label(row.get("close"), row.get("sma200"),
                             row.get("vol21"), vol_med.iloc[t])
        fut_ret = closes[t + horizon] / closes[t] - 1.0
        actual = 1 if fut_ret >= 0 else -1
        if actual == 1:
            actual_up += 1

        score = 0.0
        votes = {}
        for k, fn in engine.SUBS.items():
            v = fn(row)
            votes[k] = v
            c = cnt[(k, reg)]
            if drift:
                hr = ewma[(k, reg)]
            else:
                recent = flat[(k, reg)]
                hr = (sum(recent) / len(recent)) if recent else 0.5
            w = max(0.0, hr - 0.5)
            # encolhe peso de célula imatura (rampa linear até min_amostras) — anti-ruído
            if c < min_amostras:
                w *= c / min_amostras
            score += w * v

        ens_dir = 1 if score > 0 else (-1 if score < 0 else engine.sig_trend(row) or 1)
        if ens_dir != 0:
            ens_correct += 1 if ens_dir == actual else 0
            ens_total += 1

        # aprendizado online (drift-aware): atualiza só quem votou não-neutro
        for k in engine.SUBS:
            if votes[k] != 0:
                hit = 1 if votes[k] == actual else 0
                ewma[(k, reg)] = (1 - alpha) * ewma[(k, reg)] + alpha * hit
                flat[(k, reg)].append(hit)
                cnt[(k, reg)] += 1

    def hr(c, tot):
        return round(c / tot, 4) if tot else None
    n_eval = n - horizon - warmup
    base_up = hr(actual_up, n_eval)
    base_naive = round(max(base_up, 1 - base_up), 4) if base_up is not None else None
    ehr = hr(ens_correct, ens_total)
    edge = round(ehr - base_naive, 4) if (ehr is not None and base_naive is not None) else None
    return {"symbol": symbol, "horizon": horizon, "ensemble_hit_rate": ehr,
            "base_naive_rate": base_naive, "edge": edge, "ensemble_n": ens_total,
            "regimes": 4, "drift": drift, "half_life": half_life}


def predict_today(symbol, horizon=5, warmup=260, half_life=63, min_amostras=40,
                  vol_window=252, sentiment_series="sentiment_crypto_fng") -> dict | None:
    """Sinal direcional ATUAL pelo ensemble 4-regimes+drift: replica o estado online (EWMA por
    sub×regime) até o fim da série e aplica os pesos vigentes na última linha. Reporta o edge OOS
    do MESMO motor (honestidade: `tem_skill` reflete o que é de fato pontuado no backtest)."""
    df = engine.load_prices(symbol)
    if df.empty or len(df) < warmup + horizon + 10:
        return None
    sent = engine.load_macro(sentiment_series) if sentiment_series else None
    feats = engine.make_features(df, sent)
    closes = df["close"].values
    n = len(df)
    vol_med = feats["vol21"].rolling(vol_window, min_periods=60).median()
    alpha = _alpha_from_halflife(half_life)
    ewma = {(k, r): 0.5 for k in engine.SUBS for r in _REGS4}
    cnt = {(k, r): 0 for k in engine.SUBS for r in _REGS4}

    # replay online até a última linha avaliável (estado vigente = pesos de hoje)
    for t in range(warmup, n - horizon):
        row = feats.iloc[t]
        reg = _regime4_label(row.get("close"), row.get("sma200"), row.get("vol21"), vol_med.iloc[t])
        fut = closes[t + horizon] / closes[t] - 1.0
        actual = 1 if fut >= 0 else -1
        for k, fn in engine.SUBS.items():
            v = fn(row)
            if v != 0:
                hit = 1 if v == actual else 0
                ewma[(k, reg)] = (1 - alpha) * ewma[(k, reg)] + alpha * hit
                cnt[(k, reg)] += 1

    # sinal de HOJE: última linha, regime atual, pesos vigentes
    row = feats.iloc[-1]
    reg = _regime4_label(row.get("close"), row.get("sma200"), row.get("vol21"), vol_med.iloc[-1])
    score, detail = 0.0, {}
    for k, fn in engine.SUBS.items():
        v = fn(row)
        c = cnt[(k, reg)]
        w = max(0.0, ewma[(k, reg)] - 0.5)
        if c < min_amostras:
            w *= c / min_amostras
        score += w * v
        detail[k] = {"voto": v, "peso": round(w, 3)}
    direction = "up" if score > 0 else ("down" if score < 0 else "up")
    conf = min(0.95, 0.5 + abs(score))
    wf = walk_forward_regime4(symbol, horizon=horizon, warmup=warmup, half_life=half_life,
                              min_amostras=min_amostras, vol_window=vol_window,
                              sentiment_series=sentiment_series, drift=True)
    edge = wf.get("edge")
    return {"symbol": symbol, "direction": direction, "prob": round(conf, 3), "horizon": horizon,
            "score": round(score, 3), "detail": detail, "regime_atual": reg,
            "asof": str(df.index[-1].date()), "ensemble_oos_hit_rate": wf.get("ensemble_hit_rate"),
            "base_naive_rate": wf.get("base_naive_rate"), "edge_oos": edge,
            "tem_skill": (edge is not None and edge > 0)}


if __name__ == "__main__":
    import json
    import sys
    for s in sys.argv[1:] or ["^GSPC", "^BVSP", "BTC-USD"]:
        print(json.dumps(walk_forward_regime4(s), ensure_ascii=False))
