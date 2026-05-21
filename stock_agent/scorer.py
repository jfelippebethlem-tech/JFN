"""
Combines analysis sub-scores and formats the WhatsApp signal message.

Scoring uses learned_weights.json when available; falls back to equal weights.
The technical sub-score is re-weighted per indicator before the final blend.
"""

from datetime import datetime

import pytz

import learner


# ---------------------------------------------------------------------------
# Indicator → raw contribution (0–100 range, equal weights = 20 each)
# ---------------------------------------------------------------------------

def _raw_indicator_scores(tech: dict) -> dict[str, float]:
    """Extract each indicator's 0–20 contribution from the tech signals dict."""
    rsi = tech.get("rsi", 50)
    if rsi < 30:
        rsi_pts = 20.0
    elif rsi < 40:
        rsi_pts = 15.0
    elif rsi < 50:
        rsi_pts = 5.0
    else:
        rsi_pts = 0.0

    macd_sig = tech.get("macd_signal", "")
    if "CRUZAMENTO" in macd_sig:
        macd_pts = 20.0
    elif "ALTA" in macd_sig:
        macd_pts = 10.0
    else:
        macd_pts = 0.0

    bb_sig = tech.get("bb_signal", "")
    if "SUPORTE" in bb_sig:
        bb_pts = 20.0
    elif "ABAIXO" in bb_sig:
        bb_pts = 10.0
    else:
        bb_pts = 0.0

    trend = tech.get("trend", "")
    if "PRIMÁRIA" in trend and ("SECUNDÁRIA" in trend or "CURTO" in trend):
        ema_pts = 20.0
    elif "PRIMÁRIA" in trend:
        ema_pts = 10.0
    elif "CURTO" in trend:
        ema_pts = 5.0
    else:
        ema_pts = 0.0

    vr = tech.get("volume_ratio", 1.0)
    if vr >= 2.0:
        vol_pts = 20.0
    elif vr >= 1.5:
        vol_pts = 12.0
    elif vr >= 1.0:
        vol_pts = 5.0
    else:
        vol_pts = 0.0

    return {
        "rsi_oversold": rsi_pts / 20.0,    # normalised 0–1
        "macd_cross": macd_pts / 20.0,
        "bb_touch": bb_pts / 20.0,
        "ema_uptrend_long": ema_pts / 20.0,
        "vol_ratio": vol_pts / 20.0,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_score(tech: dict, fund: dict, sentiment: dict) -> tuple[float, str]:
    """
    Returns (combined_score 0–100, conviction_label).

    Technical sub-score is re-weighted using learned indicator weights.
    Blended 70/30 with the equal-weight score from analyzer to dampen noise.
    """
    weights = learner.load_weights()
    iw = weights.get("indicator_weights", {})
    tl = weights.get("top_level_weights", {})

    # Re-weighted technical score
    raw = _raw_indicator_scores(tech)
    iw_total = sum(iw.values()) or 1.0
    learned_tech = sum(raw.get(k, 0) * (iw.get(k, 0.20) / iw_total) for k in raw) * 100
    equal_tech = tech.get("technical_score", 0)
    # Dampen: if we have <20 signals, learned weights carry less trust
    n_signals = weights.get("meta", {}).get("n_signals", 0)
    trust = min(1.0, n_signals / 50)  # full trust at 50+ signals
    final_tech = trust * learned_tech + (1 - trust) * equal_tech

    fund_score = fund.get("fundamental_score", 50)
    sent_score = sentiment.get("sentiment_score", 60)

    tech_w = tl.get("technical", 0.50)
    fund_w = tl.get("fundamental", 0.35)
    sent_w = tl.get("sentiment", 0.15)

    total = final_tech * tech_w + fund_score * fund_w + sent_score * sent_w

    if total >= 80:
        conviction = "ALTA CONVICÇÃO"
    elif total >= 65:
        conviction = "CONVICÇÃO MODERADA"
    else:
        conviction = "SINAL FRACO"

    return round(total, 1), conviction


def format_signal_message(
    ticker: str,
    tech: dict,
    fund: dict,
    sentiment: dict,
    score: float,
    conviction: str,
    fund_raw: dict,
) -> str:
    """Build a WhatsApp-friendly signal message."""
    weights = learner.load_weights()
    n_signals = weights.get("meta", {}).get("n_signals", 0)
    baseline_wr = weights.get("meta", {}).get("baseline_win_rate")
    source = weights.get("meta", {}).get("source", "defaults")

    price = tech.get("current_price") or fund_raw.get("current_price") or 0.0
    name = fund_raw.get("name", ticker)
    sector = fund_raw.get("sector", "")

    stop = price * 0.96
    t1 = price * 1.08
    t2 = price * 1.15

    emoji = "🟢" if conviction == "ALTA CONVICÇÃO" else ("🟡" if "MODERADA" in conviction else "🔴")

    lines = [
        f"{emoji} *SINAL DE COMPRA — {conviction}*",
        "",
        f"📊 *{ticker}* | {name}",
        f"💵 Preço: R$ {price:.2f}",
    ]
    if sector:
        lines.append(f"🏭 Setor: {sector}")

    lines += ["", "📈 *ANÁLISE TÉCNICA*"]
    for key, label in [
        ("rsi_signal", f"RSI({tech.get('rsi', '?')})"),
        ("macd_signal", "MACD"),
        ("bb_signal", "Bollinger"),
        ("trend", "Tendência EMA"),
        ("volume_signal", "Volume"),
    ]:
        val = tech.get(key)
        if val:
            lines.append(f"• {label}: {val}")

    lines += ["", "💼 *ANÁLISE FUNDAMENTALISTA*"]
    has_fund = False
    for key in ["pe_signal", "roe_signal", "dy_signal", "debt_signal"]:
        val = fund.get(key)
        if val:
            lines.append(f"• {val}")
            has_fund = True
    if not has_fund:
        lines.append("• Dados indisponíveis no momento")

    lines += [
        "",
        "📰 *SENTIMENTO DE MERCADO*",
        f"• {sentiment.get('sentiment_text', 'Neutro')}",
        "",
        f"🎯 *PONTUAÇÃO: {score}/100*",
    ]

    # Learning context (shown when we have enough data)
    if source == "learned" and n_signals >= 20 and baseline_wr is not None:
        lines.append(f"🧠 _Modelo aprendido de {n_signals} sinais históricos | win rate base: {baseline_wr*100:.0f}%_")

    lines += [
        "",
        "📌 *OPERAÇÃO SUGERIDA*",
        f"• Entrada : R$ {price:.2f}",
        f"• Stop Loss: R$ {stop:.2f} (−4%)",
        f"• Alvo 1  : R$ {t1:.2f} (+8%)",
        f"• Alvo 2  : R$ {t2:.2f} (+15%)",
        f"• Alocação: 3–5% do portfólio",
        "",
        "⚠️ _Sinal automático. Não é recomendação de investimento. DYOR._",
    ]

    brt = pytz.timezone("America/Sao_Paulo")
    ts = datetime.now(brt).strftime("%H:%M %d/%m/%Y")
    lines.append(f"⏰ {ts} | B3")

    return "\n".join(lines)
