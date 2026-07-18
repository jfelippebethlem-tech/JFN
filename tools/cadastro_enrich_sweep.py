#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cadastro_enrich_sweep — enriquece o CADASTRO COMPLETO (situação, endereço, data de abertura)
dos fornecedores periciados via `lookup('registry')` (BrasilAPI→OpenCNPJ→CNPJ.ws — grátis, ungated).

POR QUÊ: o dump Empresas deu capital/porte (empresas_dump_sweep), mas situação cadastral, endereço e
data de abertura vivem no dump Estabelecimentos (que não temos). As mesmas APIs públicas por-CNPJ que
já usamos entregam tudo isso. Este sweep chama uma por CNPJ e grava na tabela `empresas` (que a
perícia lê), resolvendo os tópicos 'situacao/recencia/endereco: INDISPONIVEL'.

ALVO por VALOR (o que importa primeiro): fornecedores com maior total_pago do Estado que ainda não
têm cadastro em `empresas` (ou estão velhos). VM-safe: serial, pausa entre chamadas, cacheado no
provider (cache_ttl 24h), guarda de recursos. Idempotente (UPSERT por cnpj). Resumível (só pega o
que falta a cada rodada).

Uso:
  PYTHONPATH=. .venv/bin/python -m tools.cadastro_enrich_sweep [N] [--min-valor V]
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"

_DDL = """
CREATE TABLE IF NOT EXISTS empresas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, cnpj TEXT UNIQUE, razao_social TEXT, nome_fantasia TEXT,
    situacao TEXT, data_abertura TEXT, porte TEXT, natureza_jur TEXT, atividade_princ TEXT,
    cep TEXT, municipio TEXT, uf TEXT, capital_social REAL, raw_json TEXT, updated_at TEXT
)"""


def _guarda_recursos() -> None:
    try:
        load = float(open("/proc/loadavg").read().split()[0])
        while load >= 4:
            print(f"[cadenrich] pausa: load={load:.1f}", flush=True)
            time.sleep(20)
            load = float(open("/proc/loadavg").read().split()[0])
    except (OSError, ValueError, IndexError):
        return                              # sem /proc/loadavg → segue sem guarda (não trava)


def _alvos(con: sqlite3.Connection, limite: int, min_valor: float) -> list[tuple[str, float]]:
    """Fornecedores de maior valor SEM cadastro completo (situação nula) em `empresas`."""
    rows = con.execute(
        "SELECT f.favorecido_cpf, f.total_pago FROM favorecido_resumo f "
        "LEFT JOIN empresas e ON e.cnpj=f.favorecido_cpf "
        "WHERE length(f.favorecido_cpf)=14 AND f.total_pago>=? "
        "AND (e.cnpj IS NULL OR e.situacao IS NULL OR e.situacao='') "
        "ORDER BY f.total_pago DESC LIMIT ?", (min_valor, limite)).fetchall()
    return [(r[0], r[1] or 0.0) for r in rows]


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _upsert(con: sqlite3.Connection, cnpj: str, d: dict) -> None:
    ende = " ".join(str(d.get(k) or "") for k in ("logradouro", "numero", "bairro")).strip()
    con.execute(
        "INSERT INTO empresas (cnpj, razao_social, nome_fantasia, situacao, data_abertura, porte, "
        "natureza_jur, atividade_princ, cep, municipio, uf, capital_social, raw_json, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now')) "
        "ON CONFLICT(cnpj) DO UPDATE SET razao_social=COALESCE(excluded.razao_social,razao_social), "
        "situacao=excluded.situacao, data_abertura=excluded.data_abertura, "
        "porte=COALESCE(excluded.porte,porte), natureza_jur=COALESCE(excluded.natureza_jur,natureza_jur), "
        "cep=excluded.cep, municipio=excluded.municipio, uf=excluded.uf, "
        "capital_social=COALESCE(excluded.capital_social,capital_social), "
        "raw_json=excluded.raw_json, updated_at=datetime('now')",
        (cnpj, d.get("razao_social"), d.get("nome_fantasia") or d.get("fantasia"),
         d.get("situacao"), d.get("abertura"), d.get("porte"), d.get("natureza_jur"),
         d.get("atividade_princ") or d.get("cnae"), d.get("cep"), d.get("municipio"),
         d.get("uf"), _num(d.get("capital")),
         json.dumps({**d, "_ende": ende}, ensure_ascii=False)[:8000]))


def enriquecer(limite: int = 400, min_valor: float = 100_000.0, pausa: float = 0.5) -> dict:
    from compliance_agent.providers import lookup
    con = sqlite3.connect(str(_DB), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(_DDL)
    con.commit()
    alvos = _alvos(con, limite, min_valor)
    print(f"[cadenrich] {len(alvos)} fornecedores-alvo (≥R${min_valor:,.0f}, sem cadastro completo)",
          flush=True)
    ok = falha = 0
    t0 = time.time()
    try:
        for i, (cnpj, valor) in enumerate(alvos, 1):
            if i % 25 == 0:
                _guarda_recursos()
            try:
                r = lookup("registry", cnpj=cnpj)
            except Exception as exc:  # noqa: BLE001
                r = None
                print(f"[cadenrich] lookup falhou {cnpj}: {exc}", flush=True)
            if r and r.ok and isinstance(r.dados, dict) and r.dados.get("situacao"):
                _upsert(con, cnpj, r.dados)
                ok += 1
            else:
                falha += 1
            if i % 50 == 0:
                con.commit()
                print(f"[cadenrich] {i}/{len(alvos)} · ok={ok} falha={falha} · {time.time()-t0:.0f}s",
                      flush=True)
            time.sleep(pausa)
        con.commit()
    finally:
        n = con.execute("SELECT COUNT(*) FROM empresas WHERE situacao IS NOT NULL AND situacao<>''").fetchone()[0]
        con.close()
    print(f"[cadenrich] CONCLUÍDO: ok={ok} falha={falha} | {n:,} empresas com situação | "
          f"{time.time()-t0:.0f}s", flush=True)
    return {"alvos": len(alvos), "ok": ok, "falha": falha, "com_situacao": n}


if __name__ == "__main__":
    args = sys.argv[1:]
    lim = next((int(a) for a in args if a.isdigit()), 400)
    mv = 100_000.0
    if "--min-valor" in args:
        try:
            mv = float(args[args.index("--min-valor") + 1])
        except (IndexError, ValueError):
            mv = 100_000.0                  # arg malformado → default
    print(json.dumps(enriquecer(limite=lim, min_valor=mv), ensure_ascii=False))
