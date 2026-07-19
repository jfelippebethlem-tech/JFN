# -*- coding: utf-8 -*-
"""Coletor de PROPOSTAS de concorrentes → tabela `proposta_item` (Task 4.1 da F4 do plano-mestre).

Persiste o que hoje é EFÊMERO: os lances literais que `coletor_ata._extrair_propostas` extrai das atas
(`ata_documento`) e, quando houver texto com tabela de itens + motor LLM, os preços UNITÁRIOS por
fornecedor via `sei.extrator_precos`. É a matéria-prima dos screens de conluio (screens_conluio.py):
vetores de preços unitários iguais ±k% entre concorrentes = quase-prova de planilha compartilhada
(docs/BENCHMARKS-EXTERNOS.md §3.3).

HONESTIDADE (cláusula absoluta):
  • Só entra linha com valor NUMÉRICO LITERAL (valor_unitario ou valor_total). Sem valor → não entra.
  • Item sem CNPJ de fornecedor identificável (14 dígitos) fica FORA — sem PK não há proveniência.
  • `classificacao` só quando INTEIRO literal (rótulo textual tipo 'classificada' não vira número).
  • Sem ata do certame → 0 com log honesto. NUNCA inventa lance.

Convenção: `item = 0` (ITEM_LANCE_GLOBAL) = lance TOTAL do certame (ata sem abertura por item);
`item >= 1` = item unitário da planilha de preços (fonte='sei_precos').

Runner (NÃO roda automático; serial, commit por certame — VM 2 vCPU):
    ~/JFN/.venv/bin/python -m compliance_agent.editais.coletor_propostas --backfill [--db data/compliance.db]
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path

from compliance_agent.emendas.db import _DB_PADRAO
from compliance_agent.editais.db import conectar

log = logging.getLogger(__name__)

ITEM_LANCE_GLOBAL = 0                       # lance total da ata (sem abertura por item)
FONTES_VALIDAS = ("ata", "sei_precos")      # proveniência obrigatória — linha sem fonte válida não entra

DDL_PROPOSTA_ITEM = """CREATE TABLE IF NOT EXISTS proposta_item (
    certame TEXT NOT NULL,
    item INTEGER NOT NULL,
    fornecedor_cnpj TEXT NOT NULL,
    fornecedor_nome TEXT,
    valor_unitario REAL,
    valor_total REAL,
    classificacao INTEGER,
    marca TEXT,
    fonte TEXT,
    sha_evidencia TEXT,
    PRIMARY KEY (certame, item, fornecedor_cnpj))"""


def garantir_tabela(conn: sqlite3.Connection) -> None:
    """Cria `proposta_item` + índice por certame (aditivo, idempotente — padrão editais/db.py)."""
    conn.execute(DDL_PROPOSTA_ITEM)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_proposta_item_certame ON proposta_item(certame)")


def _so_digitos(s) -> str:
    return "".join(c for c in str(s or "") if c.isdigit())


def _num(v) -> float | None:
    """Valor numérico LITERAL (int/float). String/None → None (ausente ≠ 0; não coagimos texto)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _sha_curto(trecho: str | None) -> str | None:
    """sha256 CURTO (16 hex) do trecho de origem — âncora de evidência reproduzível."""
    if not trecho:
        return None
    return hashlib.sha256(trecho.encode("utf-8")).hexdigest()[:16]


def persistir_propostas(conn: sqlite3.Connection, certame: str, propostas: list[dict]) -> int:
    """INSERT OR REPLACE idempotente em `proposta_item`. Cada proposta (dict canônico):
    {item?, fornecedor_cnpj, fornecedor_nome?, valor_unitario?, valor_total?, classificacao?, marca?,
     fonte ('ata'|'sei_precos'), trecho?}. Devolve nº de linhas persistidas. Guards de honestidade:
    sem valor numérico literal → não entra; CNPJ != 14 dígitos → não entra; fonte inválida → não entra."""
    garantir_tabela(conn)
    n = 0
    for p in propostas or []:
        cnpj = _so_digitos(p.get("fornecedor_cnpj"))
        if len(cnpj) != 14:
            continue
        fonte = p.get("fonte")
        if fonte not in FONTES_VALIDAS:
            continue
        vu, vt = _num(p.get("valor_unitario")), _num(p.get("valor_total"))
        if vu is None and vt is None:
            continue  # sem valor literal não entra (não inventa)
        try:
            item = int(p.get("item", ITEM_LANCE_GLOBAL))
        except (TypeError, ValueError):
            continue
        classificacao = p.get("classificacao")
        if isinstance(classificacao, bool) or not isinstance(classificacao, int):
            classificacao = None  # rank só quando inteiro literal
        conn.execute(
            "INSERT OR REPLACE INTO proposta_item (certame, item, fornecedor_cnpj, fornecedor_nome, "
            "valor_unitario, valor_total, classificacao, marca, fonte, sha_evidencia) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (certame, item, cnpj, p.get("fornecedor_nome"), vu, vt, classificacao,
             p.get("marca"), fonte, _sha_curto(p.get("trecho"))))
        n += 1
    return n


# ───────────────────────────── extração (reuso: coletor_ata + extrator_precos) ─────────────────────────────
def _ler_atas(certame: str, db_path: Path | str) -> list[dict]:
    """Fontes {fonte, texto} das atas do certame — conexão READONLY, fechada logo (compliance-db-malformed)."""
    con = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    try:
        try:
            rows = con.execute(
                "SELECT titulo, texto FROM ata_documento WHERE certame=? AND texto IS NOT NULL",
                (certame,)).fetchall()
        except sqlite3.OperationalError:
            return []  # tabela ata_documento ausente neste DB — honesto: sem fonte, sem invenção
    finally:
        con.close()
    return [{"fonte": f"ata_documento '{t or 'sem título'}'", "texto": tx} for t, tx in rows if (tx or "").strip()]


def _linhas_da_ata(fontes: list[dict]) -> list[dict]:
    """Lances totais literais da ata (reusa `coletor_ata._extrair_propostas`) → dicts canônicos item=0."""
    from compliance_agent.detectores.coletor_ata import _extrair_propostas
    out = []
    for p in _extrair_propostas(fontes):
        out.append({"item": ITEM_LANCE_GLOBAL, "fornecedor_cnpj": p["licitante_cnpj"],
                    "valor_total": p["valor"], "fonte": "ata",
                    "trecho": (p.get("prov") or {}).get("trecho")})
    return out


def _linhas_unitarias(fontes: list[dict], gerar) -> list[dict]:
    """Itens unitários por fornecedor via `sei.extrator_precos.extrair_itens` (texto; camada LLM só com
    `gerar`). Item sem CNPJ ou sem valor fica fora (guard reforçado em persistir_propostas)."""
    from compliance_agent.sei.extrator_precos import extrair_itens
    out = []
    for f in fontes:
        itens, metodo, conf = extrair_itens(f["texto"], gerar=gerar)
        if not itens:
            continue
        for idx, it in enumerate(itens, start=1):
            num = _so_digitos(it.get("item"))
            trecho = " | ".join(str(it.get(k)) for k in ("item", "descricao", "marca", "valor_unitario")
                                if it.get(k) is not None)
            out.append({"item": int(num) if num else idx, "fornecedor_cnpj": it.get("cnpj"),
                        "fornecedor_nome": it.get("fornecedor"), "valor_unitario": it.get("valor_unitario"),
                        "valor_total": it.get("valor_total"), "marca": it.get("marca"),
                        "fonte": "sei_precos", "trecho": trecho or f["fonte"]})
        log.info("extrator_precos: %d itens via '%s' (conf %.1f) em %s", len(itens), metodo, conf, f["fonte"])
    return out


def coletar_certame(certame: str, db_path: Path | str | None = None, *, gerar=None) -> int:
    """Coleta e PERSISTE as propostas do certame em `proposta_item`. Devolve nº de linhas persistidas.
    Sem ata no `ata_documento` → 0 com log honesto (não inventa). `gerar` (opcional) habilita a camada
    LLM do extrator de preços unitários; sem ele, só o que o regex/tabela pegou LITERAL."""
    db = Path(db_path) if db_path else _DB_PADRAO
    fontes = _ler_atas(certame, db)
    if not fontes:
        log.info("certame %s: sem ata em ata_documento — 0 propostas (INDISPONÍVEL, não inventado)", certame)
        return 0
    linhas = _linhas_da_ata(fontes) + _linhas_unitarias(fontes, gerar)
    if not linhas:
        log.info("certame %s: ata sem lance literal (CNPJ + R$) — 0 propostas", certame)
        return 0
    con = conectar(db)
    try:
        n = persistir_propostas(con, certame, linhas)
        con.commit()
    finally:
        con.close()
    return n


# ───────────────────────────── runner de backfill (serial; NÃO roda automático) ─────────────────────────────
def backfill(db_path: Path | str | None = None, *, gerar=None) -> dict:
    """Itera os certames existentes em `ata_documento`, SERIAL, commit por certame (coletar_certame
    abre/comita/fecha por certame — VM 2 vCPU, um pesado por vez). Devolve {certames, linhas}."""
    db = Path(db_path) if db_path else _DB_PADRAO
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        certames = [r[0] for r in con.execute(
            "SELECT DISTINCT certame FROM ata_documento WHERE certame IS NOT NULL ORDER BY certame")]
    finally:
        con.close()
    total = 0
    for c in certames:
        n = coletar_certame(c, db, gerar=gerar)
        log.info("backfill %s: %d linhas", c, n)
        total += n
    return {"certames": len(certames), "linhas": total}


if __name__ == "__main__":  # pragma: no cover
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Coletor de propostas de concorrentes → proposta_item")
    ap.add_argument("--backfill", action="store_true", help="itera todos os certames de ata_documento (serial)")
    ap.add_argument("--certame", help="coleta um certame específico")
    ap.add_argument("--db", default=None, help="caminho do compliance.db (default: data/compliance.db)")
    args = ap.parse_args()
    if args.backfill:
        print(backfill(args.db))
    elif args.certame:
        print({"certame": args.certame, "linhas": coletar_certame(args.certame, args.db)})
    else:
        ap.error("use --backfill ou --certame")
