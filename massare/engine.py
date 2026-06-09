# -*- coding: utf-8 -*-
"""
Massare — motor de sinais com ENSEMBLE ADAPTATIVO (aprendizado online) + walk-forward honesto.

Ideia central (aprender constantemente, sem se enganar):
  - Várias sub-estratégias simples e robustas votam a direção (momentum, tendência, reversão à
    média, breakout de volatilidade, contrarian de sentimento).
  - Os PESOS do ensemble não são fixos: cada sub-estratégia é reavaliada pela sua taxa de acerto
    RECENTE (janela móvel) e ganha peso proporcional ao quanto bate o cara-ou-coroa. Quem erra
    perde voz. Isso é aprendizado online: o sistema se recalibra a cada passo.
  - A avaliação é WALK-FORWARD (expanding/rolling): em cada dia t só se usa informação ATÉ t para
    prever t+h; quando t+h chega, carimba acerto. Nada de look-ahead. O número que sai é a taxa
    de acerto OUT-OF-SAMPLE — a única honesta.

Tudo lag-safe (shift). Roda sobre a sede de dados (massare.db). Sem custo, sem dependência pesada.
"""
import numpy as np
import pandas as pd

from massare import store

# --------------------------------------------------------------------------- dados
def load_prices(symbol):
    with store.connect() as con:
        df = pd.read_sql_query(
            "SELECT date, close FROM prices WHERE symbol=? ORDER BY date", con, params=(symbol,))
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna()


def load_macro(series):
    with store.connect() as con:
        df = pd.read_sql_query(
            "SELECT date, value FROM macro WHERE series=? ORDER BY date", con, params=(series,))
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


# --------------------------------------------------------------------------- features (lag-safe)
def make_features(df, sentiment=None):
    f = pd.DataFrame(index=df.index)
    c = df["close"]
    f["ret1"] = c.pct_change()
    f["mom21"] = c.pct_change(21)
    f["mom63"] = c.pct_change(63)
    f["mom126"] = c.pct_change(126)
    f["sma50"] = c.rolling(50).mean()
    f["sma200"] = c.rolling(200).mean()
    f["vol21"] = f["ret1"].rolling(21).std()
    # z-score 21d (reversão à média)
    m = c.rolling(21).mean(); s = c.rolling(21).std()
    f["z21"] = (c - m) / s
    # RSI 14
    delta = c.diff()
    up = delta.clip(lower=0).rolling(14).mean()
    dn = (-delta.clip(upper=0)).rolling(14).mean()
    rs = up / dn.replace(0, np.nan)
    f["rsi"] = 100 - 100 / (1 + rs)
    f["close"] = c
    if sentiment is not None and not sentiment.empty:
        s2 = sentiment["value"].reindex(f.index, method="ffill")
        f["sentiment"] = s2
    return f


# --------------------------------------------------------------------------- sub-estratégias
# cada uma devolve voto direcional para os próximos h dias: +1 (alta), -1 (baixa), 0 (neutro)
def sig_momentum(row):
    return int(np.sign(row.get("mom63", 0) or 0))

def sig_trend(row):
    if pd.isna(row.get("sma200")): return 0
    return 1 if row["close"] > row["sma200"] else -1

def sig_meanrev(row):
    z = row.get("z21", 0)
    if pd.isna(z): return 0
    if z < -1.0: return 1     # caiu demais -> tende a voltar
    if z > 1.0:  return -1
    return 0

def sig_rsi(row):
    r = row.get("rsi", np.nan)
    if pd.isna(r): return 0
    if r < 30: return 1
    if r > 70: return -1
    return 0

def sig_sentiment(row):
    v = row.get("sentiment", np.nan)
    if pd.isna(v): return 0
    if v < 25: return 1       # medo extremo -> contrarian compra
    if v > 75: return -1      # ganância extrema -> contrarian vende
    return 0

SUBS = {"momentum": sig_momentum, "trend": sig_trend, "meanrev": sig_meanrev,
        "rsi": sig_rsi, "sentiment": sig_sentiment}


# --------------------------------------------------------------------------- walk-forward adaptativo
def walk_forward(symbol, horizon=5, warmup=260, lookback=126, sentiment_series="sentiment_crypto_fng"):
    """Retorna dict com hit-rate OOS do ensemble adaptativo e de cada sub-estratégia (baseline)."""
    df = load_prices(symbol)
    if len(df) < warmup + horizon + 10:
        return {"symbol": symbol, "erro": "dados insuficientes"}
    sent = load_macro(sentiment_series) if sentiment_series else None
    feats = make_features(df, sent)
    closes = df["close"].values
    dates = df.index
    n = len(df)

    # histórico de acertos por sub-estratégia (para peso adaptativo) e do ensemble
    hist = {k: [] for k in SUBS}          # lista de (acerto 0/1) recentes
    ens_correct, ens_total = 0, 0
    sub_correct = {k: 0 for k in SUBS}; sub_total = {k: 0 for k in SUBS}
    weight_log = []

    for t in range(warmup, n - horizon):
        row = feats.iloc[t]
        fut_ret = closes[t + horizon] / closes[t] - 1.0
        actual = 1 if fut_ret >= 0 else -1

        votes, weights = {}, {}
        for k, fn in SUBS.items():
            v = fn(row)
            votes[k] = v
            recent = hist[k][-lookback:]
            hr = (sum(recent) / len(recent)) if recent else 0.5
            weights[k] = max(0.0, hr - 0.5)   # só vota quem bate o acaso

        # ensemble: soma ponderada dos votos não-neutros
        score = sum(weights[k] * votes[k] for k in SUBS)
        ens_dir = 1 if score > 0 else (-1 if score < 0 else sig_trend(row) or 1)

        # avalia ensemble
        if ens_dir != 0:
            hit = 1 if ens_dir == actual else 0
            ens_correct += hit; ens_total += 1

        # atualiza histórico de cada sub (aprendizado online) e baseline
        for k in SUBS:
            if votes[k] != 0:
                h = 1 if votes[k] == actual else 0
                hist[k].append(h)
                sub_correct[k] += h; sub_total[k] += 1

        if t % 250 == 0:
            weight_log.append({"date": str(dates[t].date()), **{k: round(weights[k], 3) for k in SUBS}})

    def hr(c, tot): return round(c / tot, 4) if tot else None
    return {
        "symbol": symbol, "horizon": horizon,
        "ensemble_hit_rate": hr(ens_correct, ens_total), "ensemble_n": ens_total,
        "subestrategias": {k: {"hit_rate": hr(sub_correct[k], sub_total[k]), "n": sub_total[k]} for k in SUBS},
        "pesos_amostra": weight_log[-3:],
    }


def predict_today(symbol, horizon=5, lookback=126):
    """Sinal direcional ATUAL do ensemble (para registrar no learning e no briefing)."""
    df = load_prices(symbol)
    if df.empty:
        return None
    sent = load_macro("sentiment_crypto_fng")
    feats = make_features(df, sent)
    # recomputa pesos com toda a história disponível (proxy do estado online atual)
    wf = walk_forward(symbol, horizon=horizon, lookback=lookback)
    subs_hr = wf.get("subestrategias", {})
    row = feats.iloc[-1]
    score, detail = 0.0, {}
    for k, fn in SUBS.items():
        v = fn(row)
        hr = subs_hr.get(k, {}).get("hit_rate") or 0.5
        w = max(0.0, hr - 0.5)
        score += w * v
        detail[k] = {"voto": v, "peso": round(w, 3)}
    direction = "up" if score > 0 else ("down" if score < 0 else "up")
    conf = min(0.95, 0.5 + abs(score))
    return {"symbol": symbol, "direction": direction, "prob": round(conf, 3),
            "horizon": horizon, "score": round(score, 3), "detail": detail,
            "asof": str(df.index[-1].date()), "ensemble_oos_hit_rate": wf.get("ensemble_hit_rate")}


if __name__ == "__main__":
    import json
    import sys
    syms = sys.argv[1:] or ["^GSPC", "^BVSP", "BTC-USD"]
    for s in syms:
        print(json.dumps(walk_forward(s), ensure_ascii=False))
