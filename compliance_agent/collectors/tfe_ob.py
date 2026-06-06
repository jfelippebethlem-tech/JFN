# -*- coding: utf-8 -*-
"""
Coletor de TODAS as Ordens Bancárias (pagamento/liquidação) — base completa do TFE, SEM SIAFE/MFA/ADF.

Fonte: download direto `https://tfe.fazenda.rj.gov.br/tfe-download/fornecedor_ob.zip` (≈124MB), com 1 CSV
por ano (2017–2026). Cada OB traz: Data da OB, Credor (CNPJ/CPF), Nome Credor, UG, Nome UG, Órgão,
Nome Órgão, Ordem Bancária (número nominal), **Histórico** (objeto do pagamento) e **Valor OB** (pago).
É o dado de PAGAMENTO (≠ empenho). Espelho D-1 do SIAFE. Resolve "todas as OBs" que o ADF bloqueava.

Uso:
    python -m compliance_agent.collectors.tfe_ob --baixar           # baixa o zip (1x)
    python -m compliance_agent.collectors.tfe_ob --ano 2026 --ingest
"""
import argparse
import csv
import io
import os
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

_REPO = Path(__file__).resolve().parent.parent.parent
DATA = Path(os.environ.get("JFN_DATA_DIR", _REPO / "data"))
CACHE = DATA / "tfe_cache"
ZIP = CACHE / "fornecedor_ob.zip"
DB = DATA / "compliance.db"
URL = "https://tfe.fazenda.rj.gov.br/tfe-download/fornecedor_ob.zip"
UA = {"User-Agent": "Mozilla/5.0 (compatible; JFN-Auditor/1.0)"}


def baixar(force=False):
    CACHE.mkdir(parents=True, exist_ok=True)
    if ZIP.exists() and ZIP.stat().st_size > 1_000_000 and not force:
        return ZIP
    r = httpx.get(URL, headers=UA, timeout=300, verify=False, follow_redirects=True)
    ZIP.write_bytes(r.content)
    return ZIP


def _money(s):
    s = (s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_ano(ano):
    """Gera dicts de OB do ano a partir do zip."""
    if not ZIP.exists():
        baixar()
    z = zipfile.ZipFile(str(ZIP))
    nome = f"fornecedor_ob{ano}.csv"
    if nome not in z.namelist():
        raise RuntimeError(f"{nome} não está no zip")
    raw = z.read(nome).decode("latin-1", "replace")
    lines = raw.splitlines()
    hi = next((i for i, l in enumerate(lines) if l.replace('"', '').strip().startswith("Data da OB")), 0)
    for r in csv.DictReader(io.StringIO("\n".join(lines[hi:])), delimiter=";"):
        if not (r.get("Ordem Bancaria") or "").strip():
            continue
        yield r


def ingest(ano):
    """Carrega TODAS as OBs do ano em ordens_bancarias (categoria='tfe_ob'). Idempotente por ano
    (limpa o ano antes de inserir). Dedup vs SIAFE: categoria separada."""
    if not DB.exists():
        raise RuntimeError(f"banco não existe: {DB}")
    from compliance_agent.reports import categorizar as cat
    con = sqlite3.connect(str(DB))
    con.execute("CREATE INDEX IF NOT EXISTS ix_ob_numero ON ordens_bancarias(numero_ob)")
    con.execute("DELETE FROM ordens_bancarias WHERE categoria='tfe_ob' AND exercicio=?", (str(ano),))
    cols = ("numero_ob", "data_emissao", "data_pagamento", "ug_codigo", "ug_nome", "favorecido_cpf",
            "favorecido_nome", "valor", "tipo_ob", "observacao", "categoria", "exercicio")
    sql = f"INSERT INTO ordens_bancarias({','.join(cols)}) VALUES({','.join('?'*len(cols))})"
    batch, n, total = [], 0, 0.0
    for r in parse_ano(ano):
        hist = (r.get("Histórico") or "").strip()
        nome = (r.get("Nome Credor") or "").strip()
        area = cat.area_objeto(f"{nome} {hist}", "")  # categoriza pelo credor + histórico (objeto)
        v = _money(r.get("Valor OB"))
        try:
            dp = datetime.strptime((r.get("Data da OB") or "").strip(), "%d/%m/%Y").date().isoformat()
        except Exception:
            dp = f"{ano}-01-01"
        batch.append((
            (r.get("Ordem Bancaria") or "").strip(), dp, dp, (r.get("UG") or "").strip(),
            (r.get("Nome Órgão") or r.get("Nome UG") or "").strip(), (r.get("Credor") or "").strip(),
            nome, v, area, hist[:500], "tfe_ob", str(ano)))
        if v:
            total += v
        n += 1
        if len(batch) >= 5000:
            con.executemany(sql, batch); batch = []
    if batch:
        con.executemany(sql, batch)
    con.commit()
    con.close()
    return n, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baixar", action="store_true")
    ap.add_argument("--ano", type=int, default=2026)
    ap.add_argument("--ingest", action="store_true")
    a = ap.parse_args()
    if a.baixar:
        z = baixar(force=True); print(f"baixado: {z} ({z.stat().st_size:,} bytes)")
    if a.ingest:
        n, total = ingest(a.ano)
        print(f"INGERIDAS {n:,} OBs de {a.ano} | TOTAL PAGO: R$ {total:,.2f}")
    if not (a.baixar or a.ingest):
        # resumo
        cnt = sum(1 for _ in parse_ano(a.ano))
        print(f"{a.ano}: {cnt:,} OBs no arquivo.")


if __name__ == "__main__":
    main()
