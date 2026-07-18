#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""empresas_dump_sweep — popula o CADASTRO (capital social, porte, natureza) dos NOSSOS fornecedores
a partir do dump de Empresas da Receita (Dados Abertos CNPJ), VM-safe por STREAMING.

POR QUÊ: a perícia de fornecedor (investigacao_dd) mostra 'capital: INDISPONIVEL' e 'porte:
INDISPONIVEL' para ~99% dos fornecedores porque a tabela `empresas` (via BrasilAPI) só cobre ~200.
O dump Empresas tem CAPITAL SOCIAL e PORTE de TODAS as empresas — e o indício H-CAPITAL (capital
irrisório frente ao volume recebido) é um dos mais fortes de fachada. Este sweep torna esse tópico
DISPONÍVEL para todos os fornecedores nas nossas raízes.

Layout Empresas CSV (`;`-delim, latin1, SEM header):
  col1=CNPJ_BÁSICO(8) col2=RAZÃO_SOCIAL col3=NATUREZA_JUR(cód) col4=QUALIF_RESP col5=CAPITAL_SOCIAL
  (BR '0,00') col6=PORTE(00=NI,01=Micro,03=EPP,05=Demais) col7=ENTE_FEDERATIVO

NÃO tem situação cadastral, data de abertura nem endereço (esses vivem no dump Estabelecimentos, que
não temos — ficam para enriquecimento BrasilAPI dos periciados de alto valor).

Uso:  PYTHONPATH=. .venv/bin/python -m tools.empresas_dump_sweep
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"
_DUMP = _REPO / "data" / "receita_dump"
_RAIZES = _DUMP / "_nossas_raizes.txt"

_PORTE = {"00": "Não informado", "01": "Microempresa", "03": "Empresa de Pequeno Porte",
          "05": "Demais"}

_DDL = """
CREATE TABLE IF NOT EXISTS empresas_cadastro (
    cnpj_basico    TEXT PRIMARY KEY,
    razao_social   TEXT,
    natureza_cod   TEXT,
    capital_social REAL,
    porte_cod      TEXT,
    porte_txt      TEXT,
    fonte_mes      TEXT
)"""


def _carregar_raizes() -> set[str]:
    if not _RAIZES.exists():
        raise SystemExit(f"raizes não geradas: {_RAIZES}")
    return {ln.strip() for ln in _RAIZES.read_text().splitlines() if ln.strip().isdigit()}


def _conectar() -> "subprocess.sqlite3.Connection":  # type: ignore
    import sqlite3
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
            print(f"[empcad] pausa: load={load:.1f} free={free_mb}MB", flush=True)
            time.sleep(20)
            load = float(open("/proc/loadavg").read().split()[0])
            free_mb = int(subprocess.run(["free", "-m"], capture_output=True).stdout.decode()
                          .splitlines()[1].split()[6])
    except Exception as exc:  # noqa: BLE001
        print(f"[empcad] guarda-recursos indisponível: {exc}", flush=True)


def _capital(txt: str) -> float | None:
    try:
        return float((txt or "").replace(".", "").replace(",", ".")) or 0.0
    except ValueError:
        return None


def _zip_ok(zf: Path) -> bool:
    try:
        return subprocess.run(["unzip", "-l", str(zf)], capture_output=True, timeout=30).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _stream_zip(zf: Path, raizes: set[str], con, mes: str):
    proc = subprocess.Popen(["unzip", "-p", str(zf)], stdout=subprocess.PIPE, bufsize=1 << 20)
    lidas = match = 0
    buf = []
    sql = ("INSERT OR REPLACE INTO empresas_cadastro(cnpj_basico,razao_social,natureza_cod,"
           "capital_social,porte_cod,porte_txt,fonte_mes) VALUES (?,?,?,?,?,?,?)")
    try:
        for raw in proc.stdout:
            lidas += 1
            if raw[:1] != b'"':
                continue
            raiz = raw[1:9].decode("latin1", "ignore")
            if raiz not in raizes:
                continue
            p = [c.strip('"') for c in raw.decode("latin1", "ignore").rstrip("\r\n").split(";")]
            if len(p) < 6:
                continue
            porte = (p[5] or "").zfill(2) if p[5] else ""
            buf.append((p[0], p[1], p[2], _capital(p[4]), porte, _PORTE.get(porte, ""), mes))
            match += 1
            if len(buf) >= 5000:
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


def indexar(mes: str = "2026-05") -> None:
    raizes = _carregar_raizes()
    con = _conectar()
    con.execute(_DDL)
    con.execute("CREATE INDEX IF NOT EXISTS ix_empcad_cnpj ON empresas_cadastro(cnpj_basico)")
    con.commit()
    zips = sorted(_DUMP.glob("Empresas*.zip"))
    print(f"[empcad] {len(zips)} zips | {len(raizes)} raízes nossas", flush=True)
    t0 = time.time()
    tot_l = tot_m = 0
    for zf in zips:
        if not _zip_ok(zf):
            print(f"[empcad] PULA {zf.name} (zip inválido)", flush=True)
            continue
        _guarda_recursos()
        lidas, match = _stream_zip(zf, raizes, con, mes)
        tot_l += lidas
        tot_m += match
        print(f"[empcad] {zf.name}: lidas={lidas:,} match={match:,} | acum={tot_m:,} "
              f"| {time.time()-t0:.0f}s", flush=True)
    n = con.execute("SELECT COUNT(*) FROM empresas_cadastro").fetchone()[0]
    nc = con.execute("SELECT COUNT(*) FROM empresas_cadastro WHERE capital_social IS NOT NULL").fetchone()[0]
    print(f"[empcad] CONCLUÍDO: {tot_l:,} lidas | {n:,} empresas cadastradas ({nc:,} com capital) "
          f"| {time.time()-t0:.0f}s", flush=True)
    con.close()


if __name__ == "__main__":
    indexar(sys.argv[1] if len(sys.argv) > 1 else "2026-05")
