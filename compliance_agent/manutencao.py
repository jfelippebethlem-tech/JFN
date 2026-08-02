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
import gzip
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

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


def _sha256(caminho) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _sha256_descomprimido(caminho: str, metodo: str) -> str:
    """sha256 do conteúdo que sai do comprimido — sem materializar em disco."""
    h = hashlib.sha256()
    if metodo == "gzip":
        with gzip.open(caminho, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()
    pr = subprocess.Popen(["zstd", "-dc", caminho], stdout=subprocess.PIPE)
    assert pr.stdout is not None
    for b in iter(lambda: pr.stdout.read(1 << 20), b""):
        h.update(b)
    pr.wait()
    if pr.returncode != 0:
        raise RuntimeError(f"zstd -dc falhou em {caminho}")
    return h.hexdigest()


def comprimir_caches(dirs=("tfe_cache",), extensoes=(".csv",), manter=(), *,
                     metodo: str = "gzip", idade_horas: float = 0.0,
                     prefixos_manter=(), recursivo: bool = False) -> dict:
    """Comprime arquivos regeneráveis dos caches. O original sai só depois de PROVA de integridade.

    O DEFEITO QUE ISTO CORRIGE (2026-07-30). A versão anterior gravava o `.gz` e removia o original
    se `tamanho > 0`. Um `.gz` **truncado** tem tamanho > 0 — ou seja, a validação passava e o
    original ia embora. Agora compara o **sha256 do conteúdo descomprimido** com o sha256 do
    original; divergência aborta o arquivo e PRESERVA o original. Perda possível: zero byte.

    `metodo="zstd"` para JSON (rende ~15-20× contra ~6-8× do gzip; medido 20,7× nos grafos).
    `idade_horas` protege quem ainda está na janela de leitura (o cache do SEI tem TTL de 24 h).
    `prefixos_manter` é a whitelist do estado OPERACIONAL que mora junto do cache — em
    `data/sei_cache/` isso inclui o `siafe_state.json` que evita MFA por ~30 dias.
    """
    if metodo not in ("gzip", "zstd"):
        raise ValueError(f"metodo desconhecido: {metodo!r}")
    sufixo = ".gz" if metodo == "gzip" else ".zst"
    corte = time.time() - idade_horas * 3600 if idade_horas else None
    poupado = 0
    arquivos: list[dict] = []
    pulados = {"estado_vivo": 0, "recente": 0, "ja_comprimido": 0, "abortado": 0}
    for d in dirs:
        base = _DATA / d
        if not base.exists():
            continue
        for ext in extensoes:
            achados = base.rglob(f"*{ext}") if recursivo else base.glob(f"*{ext}")
            for p in sorted(achados):
                if p.name in manter or any(p.name.startswith(x) for x in prefixos_manter):
                    pulados["estado_vivo"] += 1
                    continue
                if Path(str(p) + sufixo).exists():
                    pulados["ja_comprimido"] += 1
                    continue
                if corte is not None and p.stat().st_mtime > corte:
                    pulados["recente"] += 1
                    continue
                orig = _sz(p)
                sha_orig = _sha256(p)
                destino = str(p) + sufixo
                try:
                    if metodo == "gzip":
                        with open(p, "rb") as fi, gzip.open(destino, "wb", compresslevel=9) as fo:
                            shutil.copyfileobj(fi, fo)
                    else:
                        subprocess.run(["nice", "-n", "10", "zstd", "-12", "-q", "-f",
                                        str(p), "-o", destino], check=True, capture_output=True)
                    if _sha256_descomprimido(destino, metodo) != sha_orig:
                        raise RuntimeError("sha256 do descomprimido divergiu do original")
                except Exception as exc:  # noqa: BLE001 — qualquer falha PRESERVA o original
                    logger.warning("compressão abortada em %s (%s) — original PRESERVADO",
                                   p.name, exc)
                    Path(destino).unlink(missing_ok=True)
                    pulados["abortado"] += 1
                    continue
                depois = _sz(destino)
                poupado += orig - depois
                p.unlink()
                arquivos.append({"arquivo": p.name, "antes": orig, "depois": depois})
    return {"arquivos": arquivos, "poupado": poupado, "pulados": pulados, "metodo": metodo}


def comprimir_cache_sei(idade_horas: float = 48.0) -> dict:
    """Comprime os blobs brutos de `data/sei_cache/` em zstd — 23,1 GB que ninguém mais lê inteiros.

    O QUE ISTO CONSERTA. `data/sei_cache/` tinha **25,2 GB**, dos quais **23,1 GB em 5.965 blobs
    `cdp_*.json`** (91,6%), contra 180 MB do texto já extraído em `data/sei_arquivo/` — razão de 128×.
    A política de poda existia no papel (`sei/indice.podar_cache`) e **nunca teve um caller**; pior,
    o docstring dela prometia podar `json` que o código não tocava. Não é cache: é acumulação por
    omissão, e sem entrar no cron ela volta em semanas.

    NADA É APAGADO. O original só sai depois de o sha256 do conteúdo DESCOMPRIMIDO bater com o dele
    (ver `comprimir_caches`), e a leitura fica transparente por `sei/cache_arquivo.ler_json`.

    DUAS PROTEÇÕES QUE NÃO SÃO OPCIONAIS:
      • `idade_horas=48` — o cache do SEI tem TTL de 24 h em `collectors/sei_cdp.py`; comprimir dentro
        da janela faria a leitura seguinte pagar descompressão à toa. 48 h dá folga.
      • whitelist por PREFIXO (`PREFIXOS_ESTADO_VIVO`) — este diretório NÃO é só cache: ali moram o
        `siafe_state.json` que evita MFA por ~30 dias, o lock de coleta, os checkpoints de OB, o
        `.mfa_code` e o progresso do sweep. Somados dão menos de 30 MB, e um
        `find -name '*.json' -delete` mataria dias de captura.
    """
    from compliance_agent.sei.cache_arquivo import PREFIXOS_ESTADO_VIVO

    return comprimir_caches(
        dirs=("sei_cache",), extensoes=(".json",), metodo="zstd",
        idade_horas=idade_horas, prefixos_manter=PREFIXOS_ESTADO_VIVO, recursivo=True,
    )


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
        out["comprimir_sei"] = comprimir_cache_sei()
    if tudo or podar is not None:
        out["podar"] = podar_relatorios(podar if podar is not None else 40)
    out["depois"] = relatorio()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Manutenção de storage do JFN (WAL/VACUUM/caches).")
    ap.add_argument("--tudo", action="store_true", help="checkpoint+vacuum+comprime caches+poda relatórios")
    ap.add_argument("--comprimir-caches", action="store_true",
                    help="gzip nos CSV de data/tfe_cache + zstd nos blobs brutos de data/sei_cache")
    ap.add_argument("--comprimir-sei", action="store_true",
                    help="só o zstd de data/sei_cache (blobs cdp_* com mais de 48h)")
    ap.add_argument("--podar-relatorios", type=int, metavar="N", help="mantém só os N relatórios mais recentes")
    ap.add_argument("--relatorio", action="store_true", help="só mostra tamanhos, não altera nada")
    a = ap.parse_args()
    if a.relatorio:
        print(json.dumps(relatorio(), ensure_ascii=False, indent=2))
    elif a.comprimir_sei:
        # isolado de propósito: são ~6.000 arquivos e ~23 GB; numa VM de 2 vCPU isto roda SOZINHO,
        # nunca junto do VACUUM (que reescreve um DB de 2,6 GB no mesmo disco).
        print(json.dumps(comprimir_cache_sei(), ensure_ascii=False, indent=2))
    else:
        res = manutencao(tudo=a.tudo, comprimir=a.comprimir_caches, podar=a.podar_relatorios)
        print(json.dumps(res, ensure_ascii=False, indent=2))
