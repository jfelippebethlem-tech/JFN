"""
Ingere CEIS + CNEP (Portal da Transparência/CGU, download grátis, sem chave)
na tabela local `sancoes_federais` do compliance.db.

    .venv/bin/python tools/ingerir_ceis_cnep.py [--data AAAAMMDD]

Snapshot completo a cada rodada (DROP + INSERT): o arquivo da CGU é o cadastro
inteiro do dia, não um delta. Fonte:
  https://portaldatransparencia.gov.br/download-de-dados/ceis/AAAAMMDD
  https://portaldatransparencia.gov.br/download-de-dados/cnep/AAAAMMDD
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sqlite3
import sys
import urllib.request
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DB = RAIZ / "data" / "compliance.db"
URL = "https://portaldatransparencia.gov.br/download-de-dados/{cad}/{dia}"

DDL = """
CREATE TABLE IF NOT EXISTS sancoes_federais (
    cadastro     TEXT NOT NULL,           -- CEIS | CNEP
    cpf_cnpj     TEXT NOT NULL,           -- só dígitos (11 ou 14)
    nome         TEXT,
    categoria    TEXT,
    data_inicio  TEXT,                    -- ISO AAAA-MM-DD (ou NULL)
    data_fim     TEXT,                    -- ISO; NULL = sem prazo informado
    orgao        TEXT,
    uf           TEXT,
    processo     TEXT,
    fundamentacao TEXT
);
CREATE INDEX IF NOT EXISTS ix_sancoes_doc ON sancoes_federais (cpf_cnpj);
"""


def _data_iso(s: str) -> str | None:
    s = (s or "").strip()
    try:
        return datetime.strptime(s, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def _baixar(cad: str, dia: str) -> list[dict]:
    req = urllib.request.Request(URL.format(cad=cad, dia=dia),
                                 headers={"User-Agent": "JFN-Compliance/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        blob = r.read()
    zf = zipfile.ZipFile(io.BytesIO(blob))
    nome_csv = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
    texto = zf.read(nome_csv).decode("latin-1")
    linhas = list(csv.DictReader(io.StringIO(texto), delimiter=";"))
    saida = []
    for ln in linhas:
        doc = re.sub(r"\D", "", ln.get("CPF OU CNPJ DO SANCIONADO") or "")
        if len(doc) not in (11, 14):
            continue
        saida.append({
            "cadastro": cad.upper(),
            "cpf_cnpj": doc,
            "nome": (ln.get("NOME DO SANCIONADO") or "").strip()[:300],
            "categoria": (ln.get("CATEGORIA DA SANÇÃO")
                          or ln.get("TIPO DE SANÇÃO") or "").strip()[:200],
            "data_inicio": _data_iso(ln.get("DATA INÍCIO SANÇÃO", "")),
            "data_fim": _data_iso(ln.get("DATA FINAL SANÇÃO", "")),
            "orgao": (ln.get("ÓRGÃO SANCIONADOR") or "").strip()[:300],
            "uf": (ln.get("UF ÓRGÃO SANCIONADOR") or "").strip()[:2],
            "processo": (ln.get("NÚMERO DO PROCESSO") or "").strip()[:60],
            "fundamentacao": (ln.get("FUNDAMENTAÇÃO LEGAL") or "").strip()[:300],
        })
    return saida


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None, help="AAAAMMDD (default: ontem)")
    args = ap.parse_args()
    dia = args.data or (date.today() - timedelta(days=1)).strftime("%Y%m%d")

    regs: list[dict] = []
    for cad in ("ceis", "cnep"):
        r = _baixar(cad, dia)
        print(f"{cad.upper()} {dia}: {len(r)} sanções", flush=True)
        regs.extend(r)
    if not regs:
        print("nada baixado — abortando sem tocar na tabela", flush=True)
        return 1

    con = sqlite3.connect(DB)
    try:
        con.execute("PRAGMA busy_timeout=15000")  # convive com jfn.service/backfill
        con.executescript(DDL)
        con.execute("DELETE FROM sancoes_federais")
        con.executemany(
            "INSERT INTO sancoes_federais (cadastro, cpf_cnpj, nome, categoria,"
            " data_inicio, data_fim, orgao, uf, processo, fundamentacao)"
            " VALUES (:cadastro, :cpf_cnpj, :nome, :categoria, :data_inicio,"
            " :data_fim, :orgao, :uf, :processo, :fundamentacao)", regs)
        con.commit()
        n = con.execute("SELECT COUNT(*) FROM sancoes_federais").fetchone()[0]
        print(f"sancoes_federais: {n} registros gravados", flush=True)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
