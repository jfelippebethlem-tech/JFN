"""Combines analysis scores and formats the WhatsApp signal message."""

from datetime import datetime
import pytz


def compute_score(tech: dict, fund: dict, sentiment: dict) -> tuple[float, str]:
    """
    Weighted average: technical 50%, fundamental 35%, sentiment 15%.
    Returns (score_0_to_100, conviction_label).
    """
    t = tech.get("technical_score", 0)
    f = fund.get("fundamental_score", 50)
    s = sentiment.get("sentiment_score", 60)

    total = t * 0.50 + f * 0.35 + s * 0.15

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
        "",
        "📌 *OPERAÇÃO SUGERIDA*",
        f"• Entrada: R$ {price:.2f}",
        f"• Stop Loss: R$ {stop:.2f} (−4%)",
        f"• Alvo 1: R$ {t1:.2f} (+8%)",
        f"• Alvo 2: R$ {t2:.2f} (+15%)",
        f"• Alocação: 3–5% do portfólio",
        "",
        "⚠️ _Sinal automático. Não é recomendação de investimento. Faça sua análise._",
    ]

    brt = pytz.timezone("America/Sao_Paulo")
    ts = datetime.now(brt).strftime("%H:%M %d/%m/%Y")
    lines.append(f"⏰ {ts} | B3")

    return "\n".join(lines)
