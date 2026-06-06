# Massare — super-agente de análise/predição financeira (dados gratuitos, roda na VM 24/7)

Módulo do ecossistema Mestre Jorge. Objetivo: analisar e prever movimentos de mercado (BR + EUA),
condicionado a **fundamentos + variável humana (comportamento)**, com **aprendizado contínuo** e
**medição honesta de acurácia**. Tudo com fontes 100% gratuitas, sem depender do Windows.

> 🧭 **Ambiente:** roda na VM Linux dentro de `~/JFN` (mesmo venv do JFN). É exposto ao Yoda pela API do
> JFN (`/api/massare/*` em `127.0.0.1:8000`) e trabalha durante o pregão via `massare-market.timer`.
> Visão geral do ecossistema e boot: [`../AMBIENTE.md`](../AMBIENTE.md).

## Onde os dados são agregados
**`massare/data/massare.db`** (SQLite) é a sede única. Tabelas: `prices` (OHLCV diário),
`macro` (juros/câmbio/inflação + sentimento), `assets` (catálogo), `meta`, `forecasts`
(diário de previsões), `lessons` (lições cross-agente). Robusto, consultável por SQL, idempotente.

Estado atual (backfill 2026-06-05): **25 ativos × ~20 anos** (~125 mil pregões) — Ibovespa, S&P 500,
Nasdaq, Dow, Russell, VIX, SOX (semicondutores), ouro, prata, cobre, WTI, Brent, gás, milho, soja,
alumínio, Apple/Microsoft/NVIDIA/Alphabet/Amazon, BTC, ETH, USD/BRL, EWZ. Macro: IPCA (desde 1980) +
sentimento Fear&Greed. (BCB diário longo e FRED ficam para o coletor agendado — egress da VM é lento.)

## Módulos
| Arquivo | Papel |
|---|---|
| `store.py` | esquema + upsert da sede de dados (SQLite) |
| `sources.py` | fontes grátis sem chave: Yahoo (preços 20a), BCB/SGS (macro BR), FRED CSV (macro US), Stooq, CoinGecko |
| `collect.py` | orquestra backfill (`--backfill` 20a) e atualização incremental; universo curado |
| `behavior.py` | **variável humana**: Fear&Greed, VIX, curva de juros — medo/ganância/manada |
| `learning.py` | **aprendizado contínuo**: diário de previsões avaliado contra o realizado + lições cross-agente |

## Como rodar
```bash
cd ~/JFN
./.venv/bin/python -m massare.collect --backfill   # 20 anos (1x; demora)
./.venv/bin/python -m massare.collect              # incremental (rodar no cron diário)
./.venv/bin/python -m massare.behavior             # atualiza sentimento + snapshot
./.venv/bin/python -m massare.store                # cobertura do DB
```

## A variável humana (behavioral finance)
Mercados se movem por como **humanos reagem**: medo extremo costuma marcar fundos (oportunidade),
ganância extrema marca topos (risco). `behavior.py` agrega esses proxies (Fear&Greed cripto, VIX,
spread 10Y-2Y). É **sinal de contexto, não certeza** — só vale o que o aprendizado contínuo provar.

## Aprendizado contínuo (honesto)
Toda tese vira uma **previsão registrada** (`learning.record_forecast`). Quando o futuro chega,
`grade_due()` busca o preço realizado e carimba acerto/erro; `scoreboard()` devolve a **taxa de
acerto out-of-sample real**. É assim que se persegue a meta sem se enganar: o sistema é cobrado
pelo que de fato aconteceu, não por backtest in-sample. `lessons` guarda aprendizados de todos os
agentes (Massare/JFN/Yoda/Hermes).

## Realismo (honestidade obrigatória)
**Acerto direcional >80% sustentável é irreal** (mercados quase-eficientes, não-estacionários). Alvo
honesto, segundo a literatura (López de Prado etc.): **54–56% direcional out-of-sample + Sharpe
líquido de custos > 0.8**. O que importa é a assimetria payoff×custo, não a acurácia bruta. Anti-
ilusão obrigatório: purged k-fold + embargo, custos/slippage sempre, Deflated Sharpe, walk-forward.

## Próximos passos (roadmap)
1. Coletor agendado (systemd-timer) p/ atualização diária + completar BCB/FRED com requests datados.
2. Camada de features lag-safe (pandas-ta: RSI/MACD/BB/ATR + retornos/vol + macro) com `shift(1)`.
3. Regime (HMM/hmmlearn) → roteia momentum vs mean-reversion.
4. Modelo direcional (XGBoost) vs baseline momentum; **gate**: só promove o que sobrevive OOS.
5. Backtest 2 estágios (vectorbt → backtrader com custos) + métricas honestas; relatório quantstats.
6. Integrar snapshot (preços + macro + sentimento) ao briefing diário do Yoda.

> Fontes/pesquisa: Yahoo Finance, BCB/SGS, FRED, World Bank, EIA, USGS (recursos naturais);
> vectorbt/backtrader/pandas-ta/hmmlearn/xgboost; validação López de Prado (purged CV, CPCV, DSR).
