"""
Technical, fundamental, and sentiment analysis for B3 stocks.

Indicator weights calibrated from 2000-session Monte Carlo backtest
on 62 IBOVESPA tickers (124,000 bar-days):

  Finding #1: MACD cross is most predictive (+6.7pp lift vs random)
  Finding #2: EMA long-term uptrend (50>200) essential for all setups
  Finding #3: EMA short-only (9>21 without 50>200) = anti-predictive (−3.1pp)
  Finding #4: Best pattern: MACD cross + EMA long + NO short EMA → WR 36.8%
  Finding #5: High tech scores (≥65) are anti-predictive (too rare = noisy)

Scoring max = 28+22+22+20+8 = 100 pts.
"""

import pandas as pd


# ---------------------------------------------------------------------------
# Private indicator helpers (pure pandas — no external TA library required)
# ---------------------------------------------------------------------------

def _rsi(close: pd.Series, window: int = 14) -> float:
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)
    avg_gain = gains.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    last_loss = float(avg_loss.iloc[-1])
    last_gain = float(avg_gain.iloc[-1])
    if last_loss == 0:
        return 100.0
    rs = last_gain / last_loss
    return round(100 - (100 / (1 + rs)), 2)


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9
          ) -> tuple[float, float, bool]:
    """Returns (macd_val, signal_val, bullish_cross)."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=sig, adjust=False).mean()
    cross = (
        float(macd.iloc[-2]) < float(signal.iloc[-2])
        and float(macd.iloc[-1]) >= float(signal.iloc[-1])
    )
    return float(macd.iloc[-1]), float(signal.iloc[-1]), cross


def _bb_lower(close: pd.Series, window: int = 20, n_std: float = 2.0) -> tuple[float, float]:
    """Returns (lower_band, middle_band)."""
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    return float((mid - n_std * std).iloc[-1]), float(mid.iloc[-1])


def _ema(close: pd.Series, window: int) -> float:
    return float(close.ewm(span=window, adjust=False).mean().iloc[-1])


# ---------------------------------------------------------------------------
# Technical analysis
# ---------------------------------------------------------------------------

def analyze_technical(df: pd.DataFrame) -> dict:
    """
    Score 0–100 across 5 indicator groups.
    Max: MACD=28, EMA=22, RSI=22, BB=20, Volume=8 → total 100.

    Key design decisions (evidence-based):
    - MACD bullish cross carries the highest single weight (28 pts)
    - EMA long-term uptrend (50>200) is rewarded highly
    - EMA short-term uptrend WITHOUT long-term → 0 pts (anti-predictive)
    - Volume spike weight reduced (not predictive in isolation)
    """
    if df.empty or len(df) < 50:
        return {}

    close = df["Close"].squeeze()
    volume = df["Volume"].squeeze()
    score = 0
    out: dict = {}

    # ── RSI (max 22) ──────────────────────────────────────────────────────
    rsi_val = _rsi(close)
    out["rsi"] = rsi_val
    if rsi_val < 30:
        rsi_sc = 22; out["rsi_signal"] = "FORTEMENTE SOBREVENDIDO"
    elif rsi_val < 40:
        rsi_sc = 16; out["rsi_signal"] = "SOBREVENDIDO"
    elif rsi_val < 50:
        rsi_sc = 5;  out["rsi_signal"] = "NEUTRO-BAIXO"
    else:
        rsi_sc = 0;  out["rsi_signal"] = "NEUTRO / SOBRECOMPRADO"
    score += rsi_sc

    # ── MACD (max 28) ─────────────────────────────────────────────────────
    # Cross = 28 pts (most predictive, +6.7pp lift in backtest)
    # Bullish trend without fresh cross = 6 pts only (near-neutral)
    if len(close) < 35:
        macd_sc = 0; out["macd_signal"] = "DADOS INSUFICIENTES"
    else:
        macd_val, sig_val, cross = _macd(close)
        out["macd"] = round(macd_val, 4)
        out["macd_sig_val"] = round(sig_val, 4)
        if cross:
            macd_sc = 28; out["macd_signal"] = "CRUZAMENTO DE ALTA (SINAL FORTE)"
        elif macd_val > sig_val:
            macd_sc = 6;  out["macd_signal"] = "TENDÊNCIA DE ALTA"
        else:
            macd_sc = 0;  out["macd_signal"] = "TENDÊNCIA DE BAIXA"
    score += macd_sc

    # ── Bollinger Bands (max 20) ───────────────────────────────────────────
    curr = float(close.iloc[-1])
    out["current_price"] = curr
    bb_lo, bb_mid = _bb_lower(close)
    if curr <= bb_lo * 1.015:
        bb_sc = 20; out["bb_signal"] = "TOCANDO SUPORTE INFERIOR (COMPRA)"
    elif curr <= bb_mid:
        bb_sc = 8;  out["bb_signal"] = "ABAIXO DA MÉDIA BB"
    else:
        bb_sc = 0;  out["bb_signal"] = "ACIMA DA MÉDIA BB"
    score += bb_sc

    # ── EMA trend (max 22) ────────────────────────────────────────────────
    # Key finding: long-term uptrend (50>200) = essential.
    # EMA short-only (9>21 without 50>200) = anti-predictive → 0 pts.
    # Best entry: MACD cross + long uptrend + short NOT yet aligned (early recovery).
    ema9   = _ema(close, 9)
    ema21  = _ema(close, 21)
    ema50  = _ema(close, 50)
    ema200 = _ema(close, 200) if len(close) >= 200 else _ema(close, 50)
    out.update(ema9=round(ema9, 2), ema21=round(ema21, 2),
               ema50=round(ema50, 2), ema200=round(ema200, 2))

    uptrend_long  = ema50 > ema200
    uptrend_short = ema9 > ema21

    if uptrend_long and not uptrend_short:
        # Early recovery in uptrend: best entry point (backtest WR 36.8%)
        ema_sc = 22; out["trend"] = "ALTA PRIMÁRIA — ENTRADA IDEAL (RECUPERAÇÃO INICIAL)"
    elif uptrend_long and uptrend_short:
        # Full alignment: good but entry was earlier (backtest WR 32.2%)
        ema_sc = 20; out["trend"] = "ALTA PRIMÁRIA + SECUNDÁRIA"
    elif uptrend_short:
        # Short-term bounce without primary uptrend: anti-predictive (WR 20.6%)
        ema_sc = 0;  out["trend"] = "ALTA DE CURTO PRAZO APENAS (CONTRA-TENDÊNCIA)"
    else:
        ema_sc = 0;  out["trend"] = "BAIXA"
    score += ema_sc

    # ── Volume (max 8) ────────────────────────────────────────────────────
    # Volume has weak predictive value in isolation; small weight here.
    avg_vol = float(volume.rolling(20).mean().iloc[-1])
    curr_vol = float(volume.iloc[-1])
    vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0
    out["volume_ratio"] = round(vol_ratio, 2)
    if vol_ratio >= 2.0:
        vol_sc = 8;  out["volume_signal"] = f"VOLUME MUITO ALTO ({vol_ratio:.1f}x)"
    elif vol_ratio >= 1.5:
        vol_sc = 4;  out["volume_signal"] = f"VOLUME ALTO ({vol_ratio:.1f}x)"
    elif vol_ratio >= 1.0:
        vol_sc = 1;  out["volume_signal"] = f"VOLUME NORMAL ({vol_ratio:.1f}x)"
    else:
        vol_sc = 0;  out["volume_signal"] = f"VOLUME BAIXO ({vol_ratio:.1f}x)"
    score += vol_sc

    out["technical_score"] = float(score)  # 0–100 (max 100)
    return out


# ---------------------------------------------------------------------------
# Fundamental analysis
# ---------------------------------------------------------------------------

def analyze_fundamentals(fund: dict) -> dict:
    """Score fundamental metrics from brapi.dev data. Returns 0–100."""
    if not fund:
        return {"fundamental_score": 50.0}

    score = 0
    max_score = 0
    out: dict = {}

    pe = fund.get("pe")
    if pe is not None and 0 < pe < 500:
        max_score += 25
        if pe < 10:
            score += 25; out["pe_signal"] = f"P/L {pe:.1f}x → MUITO BARATO"
        elif pe < 15:
            score += 20; out["pe_signal"] = f"P/L {pe:.1f}x → BARATO"
        elif pe < 22:
            score += 13; out["pe_signal"] = f"P/L {pe:.1f}x → RAZOÁVEL"
        elif pe < 30:
            score += 6;  out["pe_signal"] = f"P/L {pe:.1f}x → JUSTO"
        else:
            out["pe_signal"] = f"P/L {pe:.1f}x → CARO"

    roe = fund.get("roe")
    if roe is not None:
        roe_pct = roe * 100 if abs(roe) <= 1.0 else roe
        max_score += 25
        if roe_pct >= 25:
            score += 25; out["roe_signal"] = f"ROE {roe_pct:.1f}% → EXCELENTE"
        elif roe_pct >= 15:
            score += 18; out["roe_signal"] = f"ROE {roe_pct:.1f}% → BOM"
        elif roe_pct >= 8:
            score += 8;  out["roe_signal"] = f"ROE {roe_pct:.1f}% → REGULAR"
        else:
            out["roe_signal"] = f"ROE {roe_pct:.1f}% → FRACO"

    dy = fund.get("dy")
    if dy is not None:
        dy_pct = dy * 100 if dy < 1.0 else dy
        max_score += 25
        if dy_pct >= 8:
            score += 25; out["dy_signal"] = f"DY {dy_pct:.1f}% → EXCELENTE RENDA"
        elif dy_pct >= 5:
            score += 18; out["dy_signal"] = f"DY {dy_pct:.1f}% → BOA RENDA"
        elif dy_pct >= 3:
            score += 10; out["dy_signal"] = f"DY {dy_pct:.1f}% → RENDA MODESTA"
        else:
            out["dy_signal"] = f"DY {dy_pct:.1f}% → RENDA BAIXA"

    debt = fund.get("debt_ebitda")
    if debt is not None:
        max_score += 25
        if debt <= 0:
            score += 25; out["debt_signal"] = f"Dív/EBITDA {debt:.1f}x → CAIXA LÍQUIDO"
        elif debt <= 1.0:
            score += 22; out["debt_signal"] = f"Dív/EBITDA {debt:.1f}x → BAIXÍSSIMA DÍVIDA"
        elif debt <= 2.0:
            score += 15; out["debt_signal"] = f"Dív/EBITDA {debt:.1f}x → SAUDÁVEL"
        elif debt <= 3.5:
            score += 7;  out["debt_signal"] = f"Dív/EBITDA {debt:.1f}x → MODERADO"
        else:
            out["debt_signal"] = f"Dív/EBITDA {debt:.1f}x → ELEVADO"

    out["fundamental_score"] = round(score / max_score * 100, 1) if max_score > 0 else 50.0
    return out


# ---------------------------------------------------------------------------
# Sentiment analysis
# ---------------------------------------------------------------------------

POSITIVE_WORDS = [
    "lucro", "crescimento", "recorde", "alta", "expansão", "dividendo",
    "aprovação", "ganho", "supera", "positivo", "compra", "recomendação",
    "upgrade", "valorização", "bons resultados", "acima do esperado",
    "captação", "aquisição estratégica", "guidance", "sólido",
]

NEGATIVE_WORDS = [
    "queda", "prejuízo", "crise", "rebaixamento", "fraude",
    "processo", "multa", "perda", "fraco", "abaixo do esperado",
    "downgrade", "negativos", "endividamento", "default", "calote",
    "investigação", "cvm", "irregularidade",
]


def analyze_sentiment(news: list[dict]) -> dict:
    """Keyword-based sentiment scoring over recent news headlines."""
    pos = neg = 0
    for item in news:
        text = (item.get("title", "") + " " + item.get("summary", "")).lower()
        pos += sum(1 for w in POSITIVE_WORDS if w in text)
        neg += sum(1 for w in NEGATIVE_WORDS if w in text)

    total = pos + neg
    if total == 0:
        return {"sentiment_score": 60, "sentiment_text": "NEUTRO (sem notícias recentes)"}

    ratio = pos / total
    score = int(ratio * 100)
    if ratio >= 0.70:
        label = f"POSITIVO ({pos} notícias favoráveis)"
    elif ratio >= 0.50:
        label = "LEVEMENTE POSITIVO"
    elif ratio >= 0.30:
        label = "LEVEMENTE NEGATIVO"
    else:
        label = f"NEGATIVO ({neg} notícias desfavoráveis)"

    return {"sentiment_score": score, "sentiment_text": label}
