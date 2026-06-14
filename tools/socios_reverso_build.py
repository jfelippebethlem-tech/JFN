#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""socios_reverso_build — PRÉ-COMPUTA o REVERSO completo dos NOSSOS administradores, em UMA passada de stream
nos 10 Socios*.zip, gravando a tabela `socios_reverso` (pessoa -> TODOS os CNPJ_básico dela no Brasil).

POR QUÊ: `socios_reverso_grep.py` faz stream-grep nos ZIPs A CADA consulta (caro, e EXIGE os 1,9 GB de ZIPs).
Esta tabela materializa o reverso UMA vez para o conjunto BOUNDED de pessoas que nos interessa — os sócios/
administradores dos NOSSOS fornecedores (as ~25 mil pessoas distintas já em `socios_receita`). Depois disso a
REDE fica completa e consultável SEM os ZIPs, que podem ser apagados (re-baixáveis 1x/mês).

Conjunto-alvo (chave de match): (nome_norm, doc_socio) de TODA pessoa em `socios_receita`. Para cada linha dos
Socios ZIPs cujo (nome_norm + doc) bate esse conjunto, emite (doc, nome_socio, cnpj_basico, qualif_cod).
Bounded: ~dezenas de milhares de pessoas × poucos CNPJs cada.

LGPD: doc de PF já vem MASCARADO no dump (***NNNNNN**) — mantém assim, nunca desmascara.
VM-safe: STREAMING linha-a-linha via `unzip -p` (nunca carrega o ZIP); guarda de load/mem; nice(10).

Uso:
  PYTHONPATH=. .venv/bin/python -m tools.socios_reverso_build            # (re)constrói socios_reverso
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import time
import unicodedata
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"
_DUMP = _REPO / "data" / "receita_dump"

_DDL = """
CREATE TABLE IF NOT EXISTS socios_reverso (
    doc_socio    TEXT NOT NULL,      -- PF mascarado ***NNNNNN** ; PJ = CNPJ completo
    nome_socio   TEXT,
    nome_norm    TEXT,
    cnpj_basico  TEXT NOT NULL,      -- raiz (8) de um CNPJ onde a pessoa aparece (Brasil inteiro)
    qualif_cod   TEXT,
    fonte_mes    TEXT,
    PRIMARY KEY (doc_socio, nome_norm, cnpj_basico, qualif_cod)
)
"""
_IDX = [
    "CREATE INDEX IF NOT EXISTS ix_srev_docnome ON socios_reverso(doc_socio, nome_norm)",
    "CREATE INDEX IF NOT EXISTS ix_srev_cnpj    ON socios_reverso(cnpj_basico)",
]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return " ".join(s.split())


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(str(_DB), timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=60000")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def _guarda_recursos() -> None:
    try:
        load = float(open("/proc/loadavg").read().split()[0])
        free_mb = int(subprocess.run(["free", "-m"], capture_output=True).stdout.decode()
                      .splitlines()[1].split()[6])
        while load >= 4 or free_mb < 800:
            print(f"[srev] pausa: load={load:.1f} free={free_mb}MB", flush=True)
            time.sleep(20)
            load = float(open("/proc/loadavg").read().split()[0])
            free_mb = int(subprocess.run(["free", "-m"], capture_output=True).stdout.decode()
                          .splitlines()[1].split()[6])
    except Exception:
        pass


def _zip_ok(zf: Path) -> bool:
    try:
        return subprocess.run(["unzip", "-l", str(zf)], capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


def _alvo_pessoas(con: sqlite3.Connection) -> set[tuple[str, str]]:
    """Conjunto BOUNDED (nome_norm, doc_socio) dos NOSSOS sócios/admins (em socios_receita)."""
    rows = con.execute(
        "SELECT DISTINCT nome_norm, doc_socio FROM socios_receita "
        "WHERE nome_norm <> '' AND doc_socio <> ''").fetchall()
    return {(r[0], r[1]) for r in rows}


def _stream_zip(zf: Path, alvo: set[tuple[str, str]], con: sqlite3.Connection, mes: str):
    """Stream linha-a-linha; emite só linhas cujo (nome_norm, doc) ∈ alvo (nossos admins)."""
    proc = subprocess.Popen(["unzip", "-p", str(zf)], stdout=subprocess.PIPE, bufsize=1 << 20)
    lidas = match = 0
    buf = []
    BATCH = 5000
    sql = ("INSERT OR IGNORE INTO socios_reverso(doc_socio,nome_socio,nome_norm,cnpj_basico,qualif_cod,fonte_mes) "
           "VALUES (?,?,?,?,?,?)")
    try:
        for raw in proc.stdout:
            lidas += 1
            if raw[:1] != b'"':
                continue
            ln = raw.decode("latin1", "ignore").rstrip("\r\n")
            p = [c.strip('"') for c in ln.split(";")]
            if len(p) < 5:
                continue
            nome_norm = _norm(p[2])
            doc = p[3]
            if not nome_norm or not doc:
                continue
            if (nome_norm, doc) not in alvo:
                continue
            cod = (p[4] or "").zfill(2) if p[4] else ""
            buf.append((doc, p[2], nome_norm, p[0], cod, mes))
            match += 1
            if len(buf) >= BATCH:
                con.executemany(sql, buf)
                con.commit()
                buf.clear()
        if buf:
            con.executemany(sql, buf)
            con.commit()
    finally:
        proc.stdout.close()
        proc.wait()
    return lidas, match


def construir(mes: str = "2026-05") -> None:
    con = _conectar()
    con.execute(_DDL)
    for ddl in _IDX:
        con.execute(ddl)
    # reconstrução idempotente: limpa o mês corrente (tabela é derivada, sempre regenerável)
    con.execute("DELETE FROM socios_reverso")
    con.commit()

    alvo = _alvo_pessoas(con)
    if not alvo:
        raise SystemExit("socios_receita vazia — rode socios_dump_sweep antes do reverso")
    zips = sorted(_DUMP.glob("Socios*.zip"))
    if not zips:
        raise SystemExit(f"nenhum Socios*.zip em {_DUMP}")
    print(f"[srev] {len(zips)} zips | {len(alvo):,} pessoas-alvo (nossos admins)", flush=True)

    t0 = time.time()
    total_lidas = total_match = 0
    for zf in zips:
        if not _zip_ok(zf):
            print(f"[srev] PULA {zf.name} (zip incompleto/inválido)", flush=True)
            continue
        _guarda_recursos()
        lidas, match = _stream_zip(zf, alvo, con, mes)
        total_lidas += lidas
        total_match += match
        print(f"[srev] {zf.name}: lidas={lidas:,} match={match:,} | acum={total_match:,} "
              f"| {time.time()-t0:.0f}s", flush=True)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM socios_reverso").fetchone()[0]
    npess = con.execute("SELECT COUNT(DISTINCT doc_socio||'|'||nome_norm) FROM socios_reverso").fetchone()[0]
    ncnpj = con.execute("SELECT COUNT(DISTINCT cnpj_basico) FROM socios_reverso").fetchone()[0]
    print(f"[srev] CONCLUÍDO: {total_lidas:,} linhas lidas | {n:,} vínculos | {npess:,} pessoas | "
          f"{ncnpj:,} CNPJ_básico distintos | {time.time()-t0:.0f}s", flush=True)
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", default="2026-05")
    args = ap.parse_args()
    os.nice(10)
    construir(args.mes)
