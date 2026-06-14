#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""empresas_min_build — materializa `empresas_min` (cnpj_basico -> razao_social, natureza_cod) SÓ para os
cnpj_basico que aparecem em `socios_reverso`. Serve para NOMEAR as entidades ligadas na rede reversa SEM
precisar dos Empresas ZIPs (que podem ser apagados; re-baixáveis 1x/mês).

Formato Empresas CSV (`;`-delim, latin1, SEM header):
  col0=CNPJ_BÁSICO(8) col1=RAZAO_SOCIAL col2=NATUREZA_JURIDICA(cód) col3=qualif_resp col4=capital col5=porte

VM-safe: STREAMING linha-a-linha via `unzip -p`; guarda de load/mem; nice(10). Bounded pelo filtro.

Uso:
  PYTHONPATH=. .venv/bin/python -m tools.empresas_min_build
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"
_DUMP = _REPO / "data" / "receita_dump"

_DDL = """
CREATE TABLE IF NOT EXISTS empresas_min (
    cnpj_basico   TEXT PRIMARY KEY,
    razao_social  TEXT,
    natureza_cod  TEXT,
    fonte_mes     TEXT
)
"""


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
            print(f"[empmin] pausa: load={load:.1f} free={free_mb}MB", flush=True)
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


def _alvo_raizes(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT DISTINCT cnpj_basico FROM socios_reverso").fetchall()
    return {r[0] for r in rows}


def _stream_zip(zf: Path, alvo: set[str], con: sqlite3.Connection, mes: str):
    proc = subprocess.Popen(["unzip", "-p", str(zf)], stdout=subprocess.PIPE, bufsize=1 << 20)
    lidas = match = 0
    buf = []
    BATCH = 5000
    sql = ("INSERT OR REPLACE INTO empresas_min(cnpj_basico,razao_social,natureza_cod,fonte_mes) "
           "VALUES (?,?,?,?)")
    try:
        for raw in proc.stdout:
            lidas += 1
            if raw[:1] != b'"':
                continue
            raiz = raw[1:9].decode("latin1", "ignore")
            if raiz not in alvo:
                continue
            ln = raw.decode("latin1", "ignore").rstrip("\r\n")
            p = [c.strip('"') for c in ln.split(";")]
            if len(p) < 3:
                continue
            buf.append((p[0], p[1], p[2], mes))
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
    con.commit()

    alvo = _alvo_raizes(con)
    if not alvo:
        raise SystemExit("socios_reverso vazia — rode socios_reverso_build antes do empresas_min")
    zips = sorted(_DUMP.glob("Empresas*.zip"))
    if not zips:
        raise SystemExit(f"nenhum Empresas*.zip em {_DUMP}")
    print(f"[empmin] {len(zips)} zips | {len(alvo):,} cnpj_basico-alvo (do reverso)", flush=True)

    t0 = time.time()
    total_lidas = total_match = 0
    for zf in zips:
        if not _zip_ok(zf):
            print(f"[empmin] PULA {zf.name} (zip incompleto/inválido)", flush=True)
            continue
        _guarda_recursos()
        lidas, match = _stream_zip(zf, alvo, con, mes)
        total_lidas += lidas
        total_match += match
        print(f"[empmin] {zf.name}: lidas={lidas:,} match={match:,} | acum={total_match:,} "
              f"| {time.time()-t0:.0f}s", flush=True)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM empresas_min").fetchone()[0]
    print(f"[empmin] CONCLUÍDO: {total_lidas:,} linhas lidas | {n:,} empresas nomeadas "
          f"(de {len(alvo):,} alvo) | {time.time()-t0:.0f}s", flush=True)
    con.close()


if __name__ == "__main__":
    os.nice(10)
    construir()
