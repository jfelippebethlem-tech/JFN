#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coletor dos painéis da CGE-RJ (dashboards.cge.rj.gov.br, embutidos em transparencia.rj.gov.br).

Por que existe: o TFE (tfe.fazenda.rj.gov.br) recusa IP de datacenter — testado de VM-1, VM-2, WARP, GitHub,
proxy do Google Tradutor e Tor (12/11/2026). Os painéis da CGE são Streamlit, fonte SIAFE-Rio, respondem da VM
e têm botão "Gerar CSV". Exportados aqui:

  relatorio-execucao-orcamentaria-despesa → cge_execucao_despesa: Poder Executivo, 2024–ano corrente, movimento
      MENSAL por UG/grupo/modalidade/elemento/fonte (dotação, empenhado, liquidado, pago, RP). Sem AGERIO/CEDAE/IO.
  atricon4-3 (Nota de Empenho por Credor) → cge_ne_credor: NE com credor/CNPJ, licitação de origem e HISTÓRICO
      (traz nº do contrato, vigência e processo SEI em ~36% das notas) → processos_sei extraídos.

HONESTIDADE: empenho ≠ pagamento. "Despesas_pagas" da NE é o pago da nota (agregado), não OB. A fonte de OB da
casa continua sendo o SIAFE direto (ob_orcamentaria_siafe).

Grava em data/dadosabertos_rj.db (base própria). Cada exportação é completa → a tabela é SUBSTITUÍDA.

    python tools/coletar_cge_paineis.py [--so execucao|ne]
"""
import argparse
import asyncio
import json
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

import pandas as pd
from playwright.async_api import Error as PWError

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "dadosabertos_rj.db"
BRUTO = REPO / "data" / "cge_paineis"
BASE = "https://dashboards.cge.rj.gov.br"
PAINEIS = {"execucao": ("relatorio-execucao-orcamentaria-despesa", "cge_execucao_despesa"),
           "ne": ("atricon4-3", "cge_ne_credor")}
_RX_SEI = re.compile(r"\b(\d{6})/(\d{3,6})/(\d{4})\b")
_RX_CTR = re.compile(r"\b(?:CONTRATO|CTT|CT)\.?\s*(?:N[º°o]\.?\s*)?(\d{1,4}/\d{2,4})", re.I)


def coluna(nome: str) -> str:
    s = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


async def exportar(slug: str, destino: Path, espera_s: int = 25) -> Path:
    """Abre o painel, clica 'Gerar CSV' e baixa o arquivo pelo botão 'Download em CSV'."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        try:
            ctx = await b.new_context(accept_downloads=True, viewport={"width": 1400, "height": 2000})
            pg = await ctx.new_page()
            await pg.goto(f"{BASE}/{slug}/", timeout=120000)
            await pg.wait_for_timeout(espera_s * 1000)
            await pg.get_by_text("Gerar CSV").first.click()
            botao = pg.locator("button:has-text('Download'), a:has-text('Download'), button:has-text('Baixar')")
            for _ in range(120):
                await pg.wait_for_timeout(5000)
                if await botao.count():
                    break
            else:
                raise RuntimeError(f"{slug}: o botão de download não apareceu em 10 min")
            async with pg.expect_download(timeout=900000) as d:
                await botao.first.click()
            dl = await d.value
            alvo = destino / f"{time.strftime('%Y-%m-%d')}_{dl.suggested_filename}"
            await dl.save_as(str(alvo))
            return alvo
        finally:
            await b.close()


def processos(hist: str) -> list[str]:
    return sorted({f"SEI-{a}/{int(b):06d}/{c}" for a, b, c in _RX_SEI.findall(hist or "")})


def preparar(qual: str, csv: Path) -> pd.DataFrame:
    d = pd.read_csv(csv, encoding="utf-8-sig", dtype=str, low_memory=False)
    d.columns = [coluna(c) for c in d.columns]
    if qual == "execucao":
        d["ug"] = d["unidade_gestora"].str.slice(0, 6)
        d["ano"] = d["ano_consulta"].astype(int)
        d["mes"] = d["mes"].str.slice(0, 2).astype(int)
        for c in ("despesa_autorizada", "dotacao_inicial", "dotacao_atualizada", "contingenciado",
                  "despesas_empenhadas", "despesas_liquidadas", "despesas_orcamentarias_pagas",
                  "restos_a_pagar_processados_a_pagar", "restos_a_pagar_pagos", "total_desembolsado"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d = d.drop(columns=[c for c in ("codigo_ug_consulta", "limite_registros_consulta", "lote_interno",
                                        "total_lotes_internos", "posicao_no_lote") if c in d.columns])
    else:
        d["cnpj"] = d["cnpj_cpf"].str.replace(r"\D", "", regex=True)
        d["processos_sei"] = d["historico"].map(lambda h: json.dumps(processos(h)))
        d["contrato_ref"] = d["historico"].map(lambda h: (_RX_CTR.search(h or "") or [None, None])[1])
        for c in ("despesas_empenhadas", "despesas_liquidadas", "despesas_pagas"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
    return d


def gravar(tabela: str, d: pd.DataFrame, origem: Path) -> int:
    c = sqlite3.connect(DB, timeout=120)
    try:
        d.to_sql(tabela, c, if_exists="replace", index=False, chunksize=5000)
        if tabela == "cge_execucao_despesa":
            c.execute("CREATE INDEX IF NOT EXISTS ix_cge_exec ON cge_execucao_despesa(ano, mes, ug)")
        else:
            c.execute("CREATE INDEX IF NOT EXISTS ix_cge_ne ON cge_ne_credor(cnpj)")
        c.execute("CREATE TABLE IF NOT EXISTS cge_coleta (tabela TEXT PRIMARY KEY, arquivo TEXT, linhas INTEGER, "
                  "atualizado_fonte TEXT, coletado_em TEXT)")
        fonte = d["atualizado_em"].dropna().max() if "atualizado_em" in d.columns else None
        c.execute("INSERT OR REPLACE INTO cge_coleta VALUES (?,?,?,?,?)",
                  (tabela, origem.name, len(d), fonte, time.strftime("%Y-%m-%d %H:%M:%S")))
        c.commit()
    finally:
        c.close()
    return len(d)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--so", choices=list(PAINEIS))
    a = ap.parse_args()
    BRUTO.mkdir(parents=True, exist_ok=True)
    falhas = 0
    for qual, (slug, tabela) in PAINEIS.items():
        if a.so and a.so != qual:
            continue
        try:
            csv = asyncio.run(exportar(slug, BRUTO))
            n = gravar(tabela, preparar(qual, csv), csv)
            print(json.dumps({"painel": slug, "tabela": tabela, "linhas": n, "arquivo": csv.name}, ensure_ascii=False))
        except (RuntimeError, OSError, ValueError, KeyError, sqlite3.Error, PWError) as e:
            # um painel que falha não derruba o outro (PWError cobre o TimeoutError do Playwright)
            falhas += 1
            print(json.dumps({"painel": slug, "erro": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
