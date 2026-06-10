import pytest

from mestre_yoda.market import (
    MarketDataUnavailable,
    Quote,
    fetch_quotes,
    format_quotes,
)


def _fake_fetcher(table):
    def fetch(ticker):
        if ticker not in table:
            raise RuntimeError(f"sem dados para {ticker}")
        return table[ticker]
    return fetch


def test_fetch_calcula_variacao():
    fetcher = _fake_fetcher({"X": (110.0, 100.0)})
    quotes = fetch_quotes({"Ativo": "X"}, fetcher=fetcher)
    assert len(quotes) == 1
    assert quotes[0].price == 110.0
    assert quotes[0].change_pct == pytest.approx(10.0)


def test_fetch_sem_fechamento_anterior():
    fetcher = _fake_fetcher({"X": (50.0, None)})
    quotes = fetch_quotes({"Ativo": "X"}, fetcher=fetcher)
    assert quotes[0].change_pct is None


def test_fetch_pula_ticker_ruim_mas_mantem_os_bons():
    fetcher = _fake_fetcher({"BOM": (10.0, 9.0)})  # "RUIM" não está na tabela
    quotes = fetch_quotes({"Bom": "BOM", "Ruim": "RUIM"}, fetcher=fetcher)
    assert [q.ticker for q in quotes] == ["BOM"]


def test_fetch_tudo_falha_levanta():
    fetcher = _fake_fetcher({})
    with pytest.raises(MarketDataUnavailable):
        fetch_quotes({"A": "A", "B": "B"}, fetcher=fetcher)


def test_fetcher_que_sinaliza_indisponivel_propaga():
    def fetch(_):
        raise MarketDataUnavailable("fonte fora do ar")

    with pytest.raises(MarketDataUnavailable):
        fetch_quotes({"A": "A"}, fetcher=fetch)


def test_format_quotes():
    quotes = [
        Quote("Dólar", "USDBRL=X", 5.12, 0.5),
        Quote("Ouro", "GC=F", 2350.0, None),
    ]
    texto = format_quotes(quotes)
    assert "Dólar" in texto
    assert "+0.50%" in texto
    assert "Ouro" in texto


def test_render_sinal_negativo():
    q = Quote("Ibovespa", "^BVSP", 120000.0, -1.25)
    assert "(-1.25%)" in q.render()
