#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Razão social e natureza jurídica das 5,86 milhões de empresas cujo estabelecimento já temos.

A LACUNA QUE ISTO FECHA, medida em 2026-08-06 contra um caso publicado. A casa tem
`data/receita_estab.db` com **6.171.766 estabelecimentos** — endereço, telefone, e-mail, situação
cadastral, CNAE — e **não tem a razão social de nenhum deles**: a coluna simplesmente não existe no
dump Estabelecimentos. A razão social vivia só em `empresas_cadastro`/`empresas_min`, **36.192 e
141.560 raízes**, ambas curadas a partir dos nossos fornecedores.

O efeito prático era este: pedido para procurar uma empresa pelo NOME, a casa respondia "não
encontrei" quando a resposta certa era "não tenho como procurar". Foi exatamente o que aconteceu
com uma sociedade aberta em 07/2024 — a base cobre 805.855 estabelecimentos abertos depois dessa
data, e ainda assim ela era invisível, porque a busca só podia ser por CNPJ ou por nome fantasia
(que a maioria não preenche).

E A NATUREZA JURÍDICA É O QUE IDENTIFICA O TERCEIRO SETOR. Associação privada, fundação e
organização religiosa são natureza `3xxx` — a modalidade do desvio por ONG. Sem esta tabela, só
1.474 entidades de terceiro setor eram reconhecíveis; a base de estabelecimentos tem cinco milhões
de raízes esperando classificação.

CAPITAL SOCIAL vem junto porque é indício de fachada já usado na casa (capital irrisório frente ao
volume recebido) e está no mesmo registro — não custa uma passada a mais.

O RECORTE É O QUE JÁ TEMOS, e é deliberado: só entram raízes presentes em `estabelecimentos`
(5.859.921, das quais 5.851.314 no RJ). O dump nacional inteiro seriam ~63 milhões de linhas e
nenhuma delas responderia pergunta desta casa sem o endereço correspondente.

Layout Empresas CSV (`;`, latin1, sem cabeçalho):
  1=cnpj_basico 2=razao_social 3=natureza_cod 4=qualif_resp 5=capital_social(BR) 6=porte 7=ente

    python -m tools.empresas_rj_build          # constrói
    python -m tools.empresas_rj_build --medir  # só mede o que já está lá
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DUMP = _REPO / "data" / "receita_dump"
_ESTAB = _REPO / "data" / "receita_estab.db"

_SQL = """
CREATE TABLE IF NOT EXISTS empresas (
    cnpj_basico    TEXT PRIMARY KEY,
    razao_social   TEXT,
    natureza_cod   TEXT,
    capital_social REAL,
    porte_cod      TEXT,
    fonte_mes      TEXT
)"""
# Busca por NOME é o ponto inteiro desta tabela; sem o índice ela não serve para o que motivou.
_IX = ("CREATE INDEX IF NOT EXISTS ix_emp_razao ON empresas(razao_social)",
       "CREATE INDEX IF NOT EXISTS ix_emp_nat ON empresas(natureza_cod)")


def _capital(v: str) -> float:
    """'1500,00' → 1500.0. Valor ilegível vira 0.0 — e 0.0 aqui significa NÃO INFORMADO."""
    try:
        return float(str(v or "").replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def _guarda() -> None:
    """A VM tem 2 vCPU e já caiu quatro vezes. Carga alta pausa; não é opcional."""
    while True:
        with open("/proc/loadavg") as f:
            carga = float(f.read().split()[0])
        if carga < 4.0:
            return
        print(f"[empresas_rj] load {carga:.2f} — pausa 30 s", flush=True)
        time.sleep(30)


def raizes_conhecidas(estab: Path = _ESTAB) -> set[str]:
    con = sqlite3.connect(f"file:{estab}?mode=ro", uri=True)
    try:
        return {r[0] for r in con.execute("SELECT DISTINCT cnpj_basico FROM estabelecimentos")}
    finally:
        con.close()


def construir(fonte_mes: str = "2026-05", estab: Path = _ESTAB) -> dict:
    zips = sorted(_DUMP.glob("Empresas*.zip"))
    if not zips:
        raise SystemExit(f"nenhum Empresas*.zip em {_DUMP} — rode tools/baixar_receita_dump.sh empresas")
    alvo = raizes_conhecidas(estab)
    con = sqlite3.connect(str(estab), timeout=120)
    con.execute(_SQL)
    con.execute("PRAGMA journal_mode=WAL")
    t0 = time.time()
    lidas = gravadas = 0
    for z in zips:
        _guarda()
        proc = subprocess.Popen(["unzip", "-p", str(z)], stdout=subprocess.PIPE,
                                preexec_fn=lambda: os.nice(10))
        lote: list[tuple] = []
        try:
            for bruto in proc.stdout:
                lidas += 1
                p = bruto.decode("latin1", "replace").rstrip("\n").split(";")
                if len(p) < 6:
                    continue
                raiz = p[0].strip('"')
                if raiz not in alvo:
                    continue
                lote.append((raiz, p[1].strip('"').strip(), p[2].strip('"'),
                             _capital(p[4].strip('"')), p[5].strip('"'), fonte_mes))
                if len(lote) >= 5000:
                    con.executemany("INSERT OR REPLACE INTO empresas VALUES (?,?,?,?,?,?)", lote)
                    con.commit()
                    gravadas += len(lote)
                    lote.clear()
        finally:
            proc.stdout.close()
            proc.wait()
        if lote:
            con.executemany("INSERT OR REPLACE INTO empresas VALUES (?,?,?,?,?,?)", lote)
            con.commit()
            gravadas += len(lote)
        print(f"[empresas_rj] {z.name}: lidas={lidas:,} gravadas={gravadas:,}", flush=True)
    for ix in _IX:
        con.execute(ix)
    con.commit()
    con.close()
    return {"zips": len(zips), "linhas_lidas": lidas, "gravadas": gravadas,
            "raizes_alvo": len(alvo), "segundos": round(time.time() - t0, 1)}


def medir(estab: Path = _ESTAB) -> dict:
    con = sqlite3.connect(f"file:{estab}?mode=ro", uri=True)
    try:
        n = con.execute("SELECT COUNT(*) FROM empresas").fetchone()[0]
        t3 = con.execute("SELECT COUNT(*) FROM empresas WHERE substr(natureza_cod,1,1)='3'"
                         ).fetchone()[0]
        sem = con.execute("SELECT COUNT(*) FROM empresas WHERE COALESCE(razao_social,'')=''"
                          ).fetchone()[0]
        raizes = con.execute("SELECT COUNT(DISTINCT cnpj_basico) FROM estabelecimentos").fetchone()[0]
    except sqlite3.OperationalError as e:
        return {"erro": str(e)}
    finally:
        con.close()
    return {"empresas": n, "raizes_com_estabelecimento": raizes,
            "cobertura_pct": round(100.0 * n / raizes, 1) if raizes else 0.0,
            "terceiro_setor": t3, "sem_razao_social": sem}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--medir", action="store_true")
    a = ap.parse_args()
    if not a.medir:
        for k, v in construir().items():
            print(f"{k:24s} {v}")
    for k, v in medir().items():
        print(f"{k:30s} {v}")


if __name__ == "__main__":
    main()
