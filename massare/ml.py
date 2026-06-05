# -*- coding: utf-8 -*-
"""
Massare — modelos de ML: regime (HMM) + direcional (XGBoost) com validação HONESTA.

Princípios (anti-ilusão, López de Prado):
  - Features lag-safe (só passado). Target = direção do retorno futuro em `horizon` dias.
  - Walk-forward EXPANDING com PURGE: ao treinar até t, descartam-se as `horizon` linhas finais do
    treino (cujo alvo "espiaria" o futuro). Teste sempre out-of-sample.
  - Reporta hit-rate OOS + baseline (classe majoritária) — se o modelo não bate o baseline, é lixo.

Regime (HMM): GaussianHMM sobre (retorno, vol) → estados latentes (ex.: calmo-alta, calmo-baixa,
estresse). Não "prevê preço"; classifica o "clima" para condicionar a estratégia.
"""
import numpy as np
import pandas as pd

from massare import engine

FEATS = ["ret1", "mom21", "mom63", "mom126", "vol21", "z21", "rsi"]


# --------------------------------------------------------------------------- regime HMM
def regime_hmm(symbol, n_states=3, sentiment="sentiment_crypto_fng"):
    from hmmlearn.hmm import GaussianHMM
    df = engine.load_prices(symbol)
    feats = engine.make_features(df, engine.load_macro(sentiment) if sentiment else None)
    X = feats[["ret1", "vol21"]].dropna()
    if len(X) < 300:
        return {"symbol": symbol, "erro": "dados insuficientes"}
    m = GaussianHMM(n_components=n_states, covariance_type="diag", n_iter=200, random_state=42)
    m.fit(X.values)
    st = m.predict(X.values)
    out = []
    for s in range(n_states):
        mask = st == s
        out.append({"regime": int(s), "n": int(mask.sum()),
                    "ret_medio_d": round(float(X["ret1"][mask].mean()) * 100, 4),
                    "vol_med_d": round(float(X["vol21"][mask].mean()) * 100, 3)})
    # rótulo humano por (retorno, vol)
    for r in out:
        if r["vol_med_d"] > np.median([o["vol_med_d"] for o in out]) * 1.3:
            r["rotulo"] = "estresse/alta-vol"
        elif r["ret_medio_d"] >= 0:
            r["rotulo"] = "calmo-alta (bull)"
        else:
            r["rotulo"] = "calmo-baixa (bear)"
    atual = int(st[-1])
    return {"symbol": symbol, "n_estados": n_states, "regime_atual": atual,
            "rotulo_atual": next((r["rotulo"] for r in out if r["regime"] == atual), "?"),
            "regimes": out}


# --------------------------------------------------------------------------- XGBoost direcional
def xgb_walkforward(symbol, horizon=5, train_min=750, step=21):
    from xgboost import XGBClassifier
    df = engine.load_prices(symbol)
    feats = engine.make_features(df, engine.load_macro("sentiment_crypto_fng"))
    feats["fwd"] = feats["close"].shift(-horizon) / feats["close"] - 1.0
    feats["y"] = (feats["fwd"] >= 0).astype(int)
    data = feats.dropna(subset=FEATS + ["y"]).reset_index(drop=True)
    if len(data) < train_min + 100:
        return {"symbol": symbol, "erro": "dados insuficientes"}

    preds, actuals = [], []
    for t in range(train_min, len(data) - horizon, step):
        # PURGE: remove as últimas `horizon` linhas do treino (alvo espiaria o futuro)
        train = data.iloc[: t - horizon]
        test = data.iloc[t: t + step]
        if len(train) < 200 or len(test) == 0:
            continue
        m = XGBClassifier(n_estimators=120, max_depth=3, learning_rate=0.05, subsample=0.8,
                          colsample_bytree=0.8, eval_metric="logloss", verbosity=0)
        m.fit(train[FEATS].values, train["y"].values)
        preds.extend(m.predict(test[FEATS].values).tolist())
        actuals.extend(test["y"].values.tolist())

    if not preds:
        return {"symbol": symbol, "erro": "sem previsões"}
    hits = sum(1 for a, b in zip(preds, actuals) if a == b)
    base = max(np.mean(actuals), 1 - np.mean(actuals))  # baseline: prever sempre a classe majoritária
    hr = hits / len(preds)
    return {"symbol": symbol, "horizon": horizon, "n_oos": len(preds),
            "hit_rate_xgb": round(hr, 4), "baseline_majoritaria": round(float(base), 4),
            "supera_baseline": bool(hr > base)}


if __name__ == "__main__":
    import json, sys
    syms = sys.argv[1:] or ["^GSPC", "^BVSP", "^IXIC", "BTC-USD"]
    for s in syms:
        print("REGIME:", json.dumps(regime_hmm(s), ensure_ascii=False))
        print("XGB   :", json.dumps(xgb_walkforward(s), ensure_ascii=False))
