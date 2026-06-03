"""Cotações reais de mercado, via yfinance.

Migrado do bot original (rotina "BOM DIA"), que usava os mesmos tickers do
Yahoo Finance. A regra de ouro permanece: **nunca inventar dados de mercado**.
Quando a fonte real não estiver disponível, este módulo falha de forma
explícita (`MarketDataUnavailable`) para que a camada acima caia na busca na
web em vez de fabricar números.

O `yfinance` é uma dependência opcional e a busca em si é injetável, de modo que
os testes rodam sem rede.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# Rótulo legível → ticker do Yahoo Finance (os mesmos do bot original).
TICKERS: dict[str, str] = {
    "Dólar comercial (USD/BRL)": "USDBRL=X",
    "Ibovespa": "^BVSP",
    "Ouro (USD/onça)": "GC=F",
    "Petróleo WTI (USD)": "CL=F",
}

# Um fetcher recebe o ticker e devolve (preço_atual, fechamento_anterior).
# O fechamento anterior pode ser None quando a fonte não o fornece.
Fetcher = Callable[[str], "tuple[float, float | None]"]


class MarketDataUnavailable(RuntimeError):
    """A fonte real de cotações não está disponível agora."""


@dataclass(frozen=True)
class Quote:
    label: str
    ticker: str
    price: float
    change_pct: float | None

    def render(self) -> str:
        if self.change_pct is None:
            return f"{self.label}: {self.price:,.2f}"
        sinal = "+" if self.change_pct >= 0 else ""
        return f"{self.label}: {self.price:,.2f} ({sinal}{self.change_pct:.2f}%)"


def _yfinance_fetcher(ticker: str) -> tuple[float, float | None]:
    """Fetcher padrão, baseado em yfinance. Import preguiçoso e tolerante."""
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise MarketDataUnavailable("yfinance não está instalado") from exc

    info = yf.Ticker(ticker).fast_info
    price = info.get("last_price") if hasattr(info, "get") else info["last_price"]
    try:
        prev = info.get("previous_close") if hasattr(info, "get") else info["previous_close"]
    except (KeyError, AttributeError):  # pragma: no cover - varia por ticker
        prev = None
    if price is None:
        raise MarketDataUnavailable(f"sem preço para {ticker}")
    return float(price), (float(prev) if prev else None)


def fetch_quotes(
    tickers: dict[str, str] | None = None,
    *,
    fetcher: Fetcher | None = None,
) -> list[Quote]:
    """Busca as cotações pedidas. Tickers que falharem são pulados.

    Levanta `MarketDataUnavailable` apenas quando *nenhuma* cotação pôde ser
    obtida — nunca devolvendo uma lista parcial silenciosa de números falsos.
    """
    tickers = tickers or TICKERS
    fetch = fetcher or _yfinance_fetcher

    quotes: list[Quote] = []
    erros = 0
    for label, ticker in tickers.items():
        try:
            price, prev = fetch(ticker)
        except MarketDataUnavailable:
            raise
        except Exception:  # noqa: BLE001 - um ticker ruim não derruba os outros
            erros += 1
            continue
        change = None
        if prev:
            change = (price - prev) / prev * 100.0
        quotes.append(Quote(label=label, ticker=ticker, price=price, change_pct=change))

    if not quotes:
        raise MarketDataUnavailable(
            f"nenhuma cotação obtida ({erros} falha(s))"
        )
    return quotes


def format_quotes(quotes: list[Quote]) -> str:
    """Texto compacto com as cotações, uma por linha."""
    return "\n".join(q.render() for q in quotes)
