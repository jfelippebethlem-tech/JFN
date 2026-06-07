# -*- coding: utf-8 -*-
"""
Manutenção de storage do JFN — racionaliza o disco da VM sem perder dado útil.

Problema recorrente: o SQLite em modo WAL acumula um `compliance.db-wal` gigante (chegou a **2 GB**) depois de
ingestões pesadas (1,1M OBs, anomalias, contratos TCE-RJ). Os caches de coleta (CSV já ingeridos) e relatórios
antigos também incham. Este módulo:

  1. **checkpoint do WAL** (TRUNCATE) — devolve o WAL ao DB e zera o arquivo .db-wal  [maior ganho, instantâneo]
  2. **VACUUM** — reescreve o .db compactando páginas livres (INSERT OR REPLACE deixa buracos)
  3. **comprime caches** — gzip nos CSV já ingeridos de `data/tfe_cache` (regeneráveis); mantém .zip/.png
  4. **poda relatórios** antigos em `reports/` (mantém os N mais recentes por padrão)
  5. **relatório** de antes/depois

Tudo é idempotente e conservador: NUNCA apaga o .db, o .zip-fonte nem o cache do SEI. Pode rodar por cron.

CLI:
    python -m compliance_agent.manutencao                 # checkpoint + vacuum + relatório (seguro)
    python -m compliance_agent.manutencao --tudo          # + comprime caches + poda relatórios
    python -m compliance_agent.manutencao --comprimir-caches
    python -m compliance_agent.manutencao --podar-relatorios 40
    python -m compliance_agent.manutencao --relatorio     # só mostra tamanhos
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import shutil
import sqlite3
from pathlib import Path

_BASE = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
_DB = os.environ.get("JFN_DB", str(_BASE / "data" / "compliance.db"))
_DATA = _BASE / "data"
_REPORTS = _BASE / "reports"


def _sz(p) -> int:
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


def _mb(n: int) -> str:
    return f"{n/1e6:,.1f} MB"


def _dir_sz(d: Path) -> int:
    return sum(_sz(p) for p in d.rglob("*") if p.is_file()) if d.exists() else 0


def checkpoint_wal(db: str = _DB) -> dict:
    """Devolve o WAL ao banco e trunca o arquivo .db-wal (maior ganho de disco)."""
    antes = _sz(db + "-wal")
    con = sqlite3.connect(db, timeout=60)
    try:
        # garante WAL e checkpoint completo
        con.execute("PRAGMA journal_mode=WAL")
        res = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        con.commit()
    finally:
        con.close()
    return {"wal_antes": antes, "wal_depois": _sz(db + "-wal"), "pragma": res}


def vacuum(db: str = _DB) -> dict:
    """VACUUM — reescreve o .db compactando páginas livres deixadas por DELETE/INSERT OR REPLACE."""
    antes = _sz(db)
    con = sqlite3.connect(db, timeout=120)
    try:
        con.execute("VACUUM")
        con.commit()
    finally:
        con.close()
    return {"db_antes": antes, "db_depois": _sz(db)}


def analyze(db: str = _DB) -> dict:
    """ANALYZE — recolhe estatísticas (sqlite_stat1) p/ o query planner escolher índices melhores.
    Risco zero (só estatísticas); essencial num DB de 1M+ linhas e barato. Roda junto do VACUUM."""
    con = sqlite3.connect(db, timeout=120)
    try:
        con.execute("ANALYZE")
        con.commit()
        n = con.execute("SELECT COUNT(*) FROM sqlite_stat1").fetchone()[0]
    finally:
        con.close()
    return {"sqlite_stat1_linhas": n}


def comprimir_caches(dirs=("tfe_cache",), extensoes=(".csv",), manter=()) -> dict:
    """Gzip nos arquivos regeneráveis dos caches (CSV já ingeridos). Mantém .zip/.png e qualquer nome em `manter`.
    O arquivo original é removido só após o .gz ser gravado com sucesso e validado pelo tamanho."""
    poupado = 0
    arquivos = []
    for d in dirs:
        base = _DATA / d
        if not base.exists():
            continue
        for ext in extensoes:
            for p in base.glob(f"*{ext}"):
                if p.name in manter or p.with_suffix(p.suffix + ".gz").exists():
                    continue
                orig = _sz(p)
                gzpath = str(p) + ".gz"
                with open(p, "rb") as fi, gzip.open(gzpath, "wb", compresslevel=9) as fo:
                    shutil.copyfileobj(fi, fo)
                if _sz(gzpath) > 0:
                    poupado += orig - _sz(gzpath)
                    p.unlink()
                    arquivos.append({"arquivo": p.name, "antes": orig, "depois": _sz(gzpath)})
    return {"arquivos": arquivos, "poupado": poupado}


def podar_relatorios(manter: int = 40) -> dict:
    """Mantém os `manter` relatórios mais recentes (por mtime); remove o resto. Conservador: só em reports/."""
    if not _REPORTS.exists():
        return {"removidos": 0, "poupado": 0}
    arqs = sorted([p for p in _REPORTS.glob("*") if p.is_file()], key=lambda p: p.stat().st_mtime, reverse=True)
    rem, poup = 0, 0
    for p in arqs[manter:]:
        poup += _sz(p)
        p.unlink()
        rem += 1
    return {"removidos": rem, "poupado": poup}


def relatorio() -> dict:
    import shutil as _sh
    total, usado, livre = _sh.disk_usage("/")
    return {
        "disco_livre": _mb(livre),
        "db": _mb(_sz(_DB)),
        "db_wal": _mb(_sz(_DB + "-wal")),
        "tfe_cache": _mb(_dir_sz(_DATA / "tfe_cache")),
        "sei_cache": _mb(_dir_sz(_DATA / "sei_cache")),
        "reports": _mb(_dir_sz(_REPORTS)),
    }


def manutencao(tudo: bool = False, comprimir: bool = False, podar: int | None = None) -> dict:
    out = {"antes": relatorio()}
    out["checkpoint"] = checkpoint_wal()
    out["vacuum"] = vacuum()
    out["analyze"] = analyze()   # estatísticas p/ o query planner (após reescrever no VACUUM)
    # o VACUUM roda em modo WAL e regera um WAL do tamanho do DB — checkpoint final p/ truncá-lo
    out["checkpoint_pos_vacuum"] = checkpoint_wal()
    if tudo or comprimir:
        out["comprimir"] = comprimir_caches()
    if tudo or podar is not None:
        out["podar"] = podar_relatorios(podar if podar is not None else 40)
    out["depois"] = relatorio()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Manutenção de storage do JFN (WAL/VACUUM/caches).")
    ap.add_argument("--tudo", action="store_true", help="checkpoint+vacuum+comprime caches+poda relatórios")
    ap.add_argument("--comprimir-caches", action="store_true", help="gzip nos CSV regeneráveis de data/tfe_cache")
    ap.add_argument("--podar-relatorios", type=int, metavar="N", help="mantém só os N relatórios mais recentes")
    ap.add_argument("--relatorio", action="store_true", help="só mostra tamanhos, não altera nada")
    a = ap.parse_args()
    if a.relatorio:
        print(json.dumps(relatorio(), ensure_ascii=False, indent=2))
    else:
        res = manutencao(tudo=a.tudo, comprimir=a.comprimir_caches, podar=a.podar_relatorios)
        print(json.dumps(res, ensure_ascii=False, indent=2))
