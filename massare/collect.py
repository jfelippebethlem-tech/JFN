# -*- coding: utf-8 -*-
"""
Massare — coleta/backfill da sede de dados.

Uso:
    python -m massare.collect --backfill     # 20 anos de histórico (rodar 1x, demora)
    python -m massare.collect                # atualização incremental (últimos ~6 meses)
    python -m massare.collect --macro        # só macro (BCB + FRED)

Universo curado (expansível em UNIVERSE/MACRO). Tudo via fontes gratuitas sem chave.
"""
import argparse
import sys
import time

from massare import store
from massare import sources

# símbolo Yahoo, nome, classe, região, moeda
UNIVERSE = [
    # Índices BR / câmbio
    ("^BVSP",   "Ibovespa",            "index",     "BR", "BRL"),
    ("USDBRL=X","Dólar/Real",          "fx",        "BR", "BRL"),
    ("EWZ",     "iShares Brazil ETF",  "etf",       "US", "USD"),
    # Índices EUA
    ("^GSPC",   "S&P 500",             "index",     "US", "USD"),
    ("^IXIC",   "Nasdaq Composite",    "index",     "US", "USD"),
    ("^DJI",    "Dow Jones",           "index",     "US", "USD"),
    ("^RUT",    "Russell 2000",        "index",     "US", "USD"),
    ("^VIX",    "VIX (volatilidade)",  "index",     "US", "USD"),
    ("^SOX",    "PHLX Semiconductores","index",     "US", "USD"),
    # Commodities / recursos naturais
    ("GC=F",    "Ouro",                "commodity", "US", "USD"),
    ("SI=F",    "Prata",               "commodity", "US", "USD"),
    ("HG=F",    "Cobre",               "commodity", "US", "USD"),
    ("CL=F",    "Petróleo WTI",        "commodity", "US", "USD"),
    ("BZ=F",    "Petróleo Brent",      "commodity", "US", "USD"),
    ("NG=F",    "Gás Natural",         "commodity", "US", "USD"),
    ("ZC=F",    "Milho",               "commodity", "US", "USD"),
    ("ZS=F",    "Soja",                "commodity", "US", "USD"),
    ("ALI=F",   "Alumínio",            "commodity", "US", "USD"),
    # Tecnologia (líderes)
    ("AAPL",    "Apple",               "stock",     "US", "USD"),
    ("MSFT",    "Microsoft",           "stock",     "US", "USD"),
    ("NVDA",    "NVIDIA",              "stock",     "US", "USD"),
    ("GOOGL",   "Alphabet",            "stock",     "US", "USD"),
    ("AMZN",    "Amazon",              "stock",     "US", "USD"),
    # Cripto
    ("BTC-USD", "Bitcoin",             "crypto",    "US", "USD"),
    ("ETH-USD", "Ethereum",            "crypto",    "US", "USD"),
]

# séries macro: (id, nome, fonte) — fonte 'bcb' usa código SGS, 'fred' usa id FRED
MACRO = [
    ("1",   "PTAX dólar venda",        "bcb"),
    ("432", "Selic meta (% a.a.)",     "bcb"),
    ("433", "IPCA mensal (%)",         "bcb"),
    ("4389","CDI (% a.a.)",            "bcb"),
    ("DGS10",  "Treasury 10Y (%)",     "fred"),
    ("DFF",    "Fed Funds (%)",        "fred"),
    ("T10Y2Y", "Spread 10Y-2Y",        "fred"),
    ("CPIAUCSL","CPI EUA (índice)",    "fred"),
    ("UNRATE", "Desemprego EUA (%)",   "fred"),
    ("DCOILWTICO","WTI spot (FRED)",   "fred"),
]


def collect_prices(rng):
    ok, fail = 0, 0
    for sym, name, kind, region, ccy in UNIVERSE:
        store.upsert_asset(sym, name, kind, region, ccy, "yahoo")
        try:
            rows = sources.yahoo_history(sym, rng=rng)
            n = store.upsert_prices(rows, "yahoo")
            print(f"  ✓ {sym:10} {name:24} {n:5} pregões")
            ok += 1
        except Exception as e:
            print(f"  ✗ {sym:10} {name:24} FALHOU: {type(e).__name__} {str(e)[:60]}")
            fail += 1
        time.sleep(0.6)  # gentil com a API
    return ok, fail


def collect_macro():
    ok, fail = 0, 0
    for sid, name, src in MACRO:
        try:
            rows = sources.bcb_series(sid) if src == "bcb" else sources.fred_series(sid)
            n = store.upsert_macro(name, rows, src)
            span = f"{rows[0][0]}→{rows[-1][0]}" if rows else "vazio"
            print(f"  ✓ {name:24} {n:6} pts  {span}")
            ok += 1
        except Exception as e:
            print(f"  ✗ {name:24} FALHOU: {type(e).__name__} {str(e)[:60]}")
            fail += 1
        time.sleep(0.5)
    return ok, fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="20 anos de histórico")
    ap.add_argument("--macro", action="store_true", help="só macro")
    args = ap.parse_args()

    store.init_db()
    rng = "20y" if args.backfill else "6mo"

    if not args.macro:
        print(f"== PREÇOS ({rng}) ==")
        po, pf = collect_prices(rng)
    else:
        po = pf = 0

    print("== MACRO (BCB + FRED) ==")
    mo, mf = collect_macro()

    store.set_meta("last_collect", time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))
    store.set_meta("last_mode", "backfill" if args.backfill else ("macro" if args.macro else "incremental"))

    px, mac = store.coverage()
    total_pregoes = sum(r[1] for r in px)
    print(f"\n== RESUMO ==")
    print(f"  símbolos: {len(px)} | total de pregões no DB: {total_pregoes:,}")
    print(f"  séries macro: {len(mac)}")
    print(f"  preços OK/FALHA: {po}/{pf} | macro OK/FALHA: {mo}/{mf}")
    return 0 if pf == 0 and mf == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
