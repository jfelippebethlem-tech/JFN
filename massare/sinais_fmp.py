# -*- coding: utf-8 -*-
"""
Massare — SINAIS DIFERENCIADOS do FMP (senate/congresso, insider) materializados em massare.db.

⚠️ COLETOR DORMENTE (verificado 06-11): esses endpoints por-símbolo são PAGOS — tanto na chave REST grátis
(402) QUANTO no MCP do FMP, que retornou ACCESS DENIED para `senate-trading`/`search-insider-trades` (exige
plano Starter+). Só os feeds "latest" amplos e o macro responderam no tier atual. Logo este módulo fica
PRONTO mas DORMENTE: ativa quando houver plano FMP pago (o Claude puxa pelo MCP e GRAVA aqui; o motor lê da
tabela) ou via os feeds amplos filtrados. Honesto: proveniência (fonte_url) por linha; buy/sell, nunca
recomendação garantida; INDISPONÍVEL (sem plano) ≠ ausência de sinal.

Normalizadores (`_norm_senate`, `_norm_insider`) são PUROS (testáveis sem rede). `gravar` faz UPSERT
idempotente. `resumo_por_symbol` agrega o sinal recente (net buy−sell) p/ o motor consumir.
"""
from __future__ import annotations

import time

from massare import store

SCHEMA = """
CREATE TABLE IF NOT EXISTS sinais_fmp (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo        TEXT,                 -- 'senate' | 'house' | 'insider'
    symbol      TEXT,
    data        TEXT,                 -- data da transação (YYYY-MM-DD)
    ator        TEXT,                 -- político (nome/office) ou insider (reportingName)
    operacao    TEXT,                 -- 'buy' | 'sell'
    detalhe     TEXT,                 -- faixa de valor / cargo / qtd@preço
    fonte_url   TEXT,
    coletado_em TEXT,
    UNIQUE(tipo, symbol, data, ator, operacao, detalhe)
);
CREATE INDEX IF NOT EXISTS ix_sinais_fmp_symbol ON sinais_fmp(symbol);
"""


def init():
    with store.connect() as con:
        con.executescript(SCHEMA)


def _op_senate(tipo_txt: str) -> str:
    return "buy" if "purchase" in (tipo_txt or "").lower() else "sell"


def _norm_senate(rows, tipo: str = "senate") -> list[dict]:
    """Linhas do FMP senate/house → registros normalizados (PURO)."""
    out = []
    for r in rows or []:
        sym = (r.get("symbol") or "").strip().upper()
        if not sym:
            continue
        ator = (r.get("office") or f"{r.get('firstName','')} {r.get('lastName','')}").strip()
        out.append({
            "tipo": tipo, "symbol": sym, "data": r.get("transactionDate") or r.get("disclosureDate"),
            "ator": ator, "operacao": _op_senate(r.get("type")),
            "detalhe": (r.get("amount") or "").strip(), "fonte_url": r.get("link") or "",
        })
    return out


def _norm_insider(rows) -> list[dict]:
    """Linhas do FMP insider (Form 4) → registros normalizados (PURO). A=aquisição(buy), D=disposição(sell)."""
    out = []
    for r in rows or []:
        sym = (r.get("symbol") or "").strip().upper()
        if not sym:
            continue
        op = "buy" if (r.get("acquisitionOrDisposition") or "").upper() == "A" else "sell"
        qtd = r.get("securitiesTransacted")
        preco = r.get("price")
        detalhe = f"{(r.get('typeOfOwner') or '').strip()} · {qtd}@{preco}".strip(" ·")
        out.append({
            "tipo": "insider", "symbol": sym, "data": r.get("transactionDate") or r.get("filingDate"),
            "ator": (r.get("reportingName") or "").strip(), "operacao": op,
            "detalhe": detalhe, "fonte_url": r.get("url") or "",
        })
    return out


def gravar(registros: list[dict]) -> int:
    """UPSERT idempotente dos sinais normalizados. Retorna nº de linhas novas."""
    init()
    now = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    n = 0
    with store.connect() as con:
        for r in registros:
            cur = con.execute(
                """INSERT OR IGNORE INTO sinais_fmp(tipo,symbol,data,ator,operacao,detalhe,fonte_url,coletado_em)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (r.get("tipo"), r.get("symbol"), r.get("data"), r.get("ator"),
                 r.get("operacao"), r.get("detalhe"), r.get("fonte_url"), now))
            n += cur.rowcount
    return n


def resumo_por_symbol(symbol: str, dias: int = 90) -> dict:
    """Sinal agregado recente de um ticker: nº de buys/sells por tipo + viés (net = buys − sells)."""
    init()
    corte = time.strftime("%Y-%m-%d", time.gmtime(time.time() - dias * 86400))
    sym = (symbol or "").strip().upper()
    out = {"symbol": sym, "janela_dias": dias, "por_tipo": {}, "net": 0, "n": 0}
    with store.connect() as con:
        rows = con.execute(
            "SELECT tipo, operacao, COUNT(*) FROM sinais_fmp WHERE symbol=? AND data>=? GROUP BY tipo, operacao",
            (sym, corte)).fetchall()
    for tipo, op, c in rows:
        t = out["por_tipo"].setdefault(tipo, {"buy": 0, "sell": 0})
        t[op] = c
        out["n"] += c
        out["net"] += c if op == "buy" else -c
    out["vies"] = "comprador" if out["net"] > 0 else ("vendedor" if out["net"] < 0 else "neutro")
    return out
