"""Technical, fundamental, and sentiment analysis for B3 stocks."""

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator
from ta.volatility import BollingerBands


# ---------------------------------------------------------------------------
# Technical analysis
# ---------------------------------------------------------------------------

def analyze_technical(df: pd.DataFrame) -> dict:
    """
    Runs RSI, MACD, Bollinger Bands, EMA trend, and volume analysis.
    Returns a dict with individual signals and a 0–100 technical_score.
    Requires at least 50 rows of OHLCV data.
    """
    if df.empty or len(df) < 50:
        return {}

    close = df["Close"].squeeze()
    volume = df["Volume"].squeeze()

    score = 0
    max_score = 0
    out: dict = {}

    # --- RSI ---
    rsi_val = float(RSIIndicator(close, window=14).rsi().iloc[-1])
    out["rsi"] = round(rsi_val, 1)
    max_score += 20
    if rsi_val < 30:
        score += 20
        out["rsi_signal"] = "FORTEMENTE SOBREVENDIDO"
    elif rsi_val < 40:
        score += 15
        out["rsi_signal"] = "SOBREVENDIDO"
    elif rsi_val < 50:
        score += 5
        out["rsi_signal"] = "NEUTRO-BAIXO"
    else:
        out["rsi_signal"] = "NEUTRO / SOBRECOMPRADO"

    # --- MACD ---
    macd_ind = MACD(close)
    macd_line = macd_ind.macd()
    sig_line = macd_ind.macd_signal()
    out["macd"] = round(float(macd_line.iloc[-1]), 4)
    out["macd_sig"] = round(float(sig_line.iloc[-1]), 4)
    max_score += 20
    bullish_cross = (
        float(macd_line.iloc[-2]) < float(sig_line.iloc[-2])
        and float(macd_line.iloc[-1]) > float(sig_line.iloc[-1])
    )
    if bullish_cross:
        score += 20
        out["macd_signal"] = "CRUZAMENTO DE ALTA (FORTE)"
    elif float(macd_line.iloc[-1]) > float(sig_line.iloc[-1]):
        score += 10
        out["macd_signal"] = "TENDÊNCIA DE ALTA"
    else:
        out["macd_signal"] = "TENDÊNCIA DE BAIXA"

    # --- Bollinger Bands ---
    bb = BollingerBands(close, window=20)
    bb_low = float(bb.bollinger_lband().iloc[-1])
    bb_high = float(bb.bollinger_hband().iloc[-1])
    curr = float(close.iloc[-1])
    out["current_price"] = curr
    bb_range = bb_high - bb_low if bb_high != bb_low else 1
    out["bb_position"] = round((curr - bb_low) / bb_range * 100, 1)
    max_score += 20
    if curr <= bb_low * 1.01:
        score += 20
        out["bb_signal"] = "TOCANDO SUPORTE INFERIOR (COMPRA)"
    elif curr <= float(bb.bollinger_mavg().iloc[-1]):
        score += 10
        out["bb_signal"] = "ABAIXO DA MÉDIA BB"
    else:
        out["bb_signal"] = "ACIMA DA MÉDIA BB"

    # --- EMA trend ---
    ema9 = float(EMAIndicator(close, window=9).ema_indicator().iloc[-1])
    ema21 = float(EMAIndicator(close, window=21).ema_indicator().iloc[-1])
    ema50 = float(EMAIndicator(close, window=50).ema_indicator().iloc[-1])
    ema200 = float(EMAIndicator(close, window=200).ema_indicator().iloc[-1]) if len(df) >= 200 else ema50
    out.update(ema9=round(ema9, 2), ema21=round(ema21, 2), ema50=round(ema50, 2), ema200=round(ema200, 2))
    max_score += 20
    uptrend_long = ema50 > ema200
    uptrend_short = ema9 > ema21
    if uptrend_long and uptrend_short:
        score += 20
        out["trend"] = "ALTA PRIMÁRIA + SECUNDÁRIA"
    elif uptrend_long:
        score += 10
        out["trend"] = "ALTA PRIMÁRIA"
    elif uptrend_short:
        score += 5
        out["trend"] = "ALTA DE CURTO PRAZO"
    else:
        out["trend"] = "BAIXA"

    # --- Volume spike ---
    avg_vol = float(volume.rolling(20).mean().iloc[-1])
    curr_vol = float(volume.iloc[-1])
    vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0
    out["volume_ratio"] = round(vol_ratio, 2)
    max_score += 20
    if vol_ratio >= 2.0:
        score += 20
        out["volume_signal"] = f"VOLUME MUITO ALTO ({vol_ratio:.1f}x)"
    elif vol_ratio >= 1.5:
        score += 12
        out["volume_signal"] = f"VOLUME ALTO ({vol_ratio:.1f}x)"
    elif vol_ratio >= 1.0:
        score += 5
        out["volume_signal"] = f"VOLUME NORMAL ({vol_ratio:.1f}x)"
    else:
        out["volume_signal"] = f"VOLUME BAIXO ({vol_ratio:.1f}x)"

    out["technical_score"] = round(score / max_score * 100, 1)
    return out


# ---------------------------------------------------------------------------
# Fundamental analysis
# ---------------------------------------------------------------------------

def analyze_fundamentals(fund: dict) -> dict:
    """Score fundamental metrics from brapi.dev data."""
    if not fund:
        return {"fundamental_score": 50.0}

    score = 0
    max_score = 0
    out: dict = {}

    # P/L — lower is better for value
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
            score += 6; out["pe_signal"] = f"P/L {pe:.1f}x → JUSTO"
        else:
            out["pe_signal"] = f"P/L {pe:.1f}x → CARO"

    # ROE — higher is better
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

    # Dividend Yield — higher is better
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

    # Dívida Líq/EBITDA — lower is better
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
    "queda", "prejuízo", "crise", "rebaixamento", "dívida", "fraude",
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
