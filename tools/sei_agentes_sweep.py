#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Varre o acervo SEI capturado e persiste QUEM responde por cada processo.

Alimenta duas verificações com fundamento expresso (ver `sei/agentes_publicos.montar_ficha`):
  · art. 117 da Lei 14.133/2021 — execução contratual sem fiscal formalmente designado;
  · art. 5º da Lei 14.133/2021 — ordenador de despesas que também atesta a execução
    (quebra de segregação de funções).

Determinístico, sem rede, sem LLM. Escreve em `agente_processo` e `agente_lacuna`.
Educado com a VM (2 vCPU): lê texto já capturado, um processo por vez.

    .venv/bin/python tools/sei_agentes_sweep.py [--limite N] [--so-conta]
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from compliance_agent.sei.agentes_publicos import (  # noqa: E402
    PAPEIS_DECISORIOS, PAPEIS_FISCALIZACAO, montar_ficha,
)

ACERVO = pathlib.Path(os.environ.get("JFN_SEI_ARQUIVO", "data/sei_arquivo"))
DB = os.environ.get("JFN_DB", "data/compliance.db")
MAX_DOCS_POR_PROCESSO = 60


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS agente_processo (
            processo TEXT, nome TEXT, papel TEXT, id_funcional TEXT, matricula TEXT,
            cargo TEXT, origem TEXT, documento TEXT, contexto TEXT, visto_em TEXT,
            PRIMARY KEY (processo, nome, papel)
        );
        CREATE INDEX IF NOT EXISTS ix_agente_nome ON agente_processo(nome);
        CREATE INDEX IF NOT EXISTS ix_agente_papel ON agente_processo(papel);
        CREATE INDEX IF NOT EXISTS ix_agente_id ON agente_processo(id_funcional);
        CREATE TABLE IF NOT EXISTS agente_lacuna (
            processo TEXT, tipo TEXT, descricao TEXT, visto_em TEXT,
            PRIMARY KEY (processo, tipo)
        );
    """)
    con.commit()


def _textos(pasta: pathlib.Path) -> dict[str, str]:
    td = pasta / "texto"
    if not td.is_dir():
        return {}
    docs: dict[str, str] = {}
    for f in sorted(td.glob("*.txt"))[:MAX_DOCS_POR_PROCESSO]:
        try:
            docs[f.name] = f.read_text(errors="replace")
        except OSError:
            continue
    return docs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--so-conta", action="store_true",
                    help="mede e imprime, sem gravar no banco")
    args = ap.parse_args()

    if not ACERVO.is_dir():
        print(f"acervo não encontrado: {ACERVO}", file=sys.stderr)
        return 2

    con = None
    if not args.so_conta:
        con = sqlite3.connect(DB, timeout=60)
        init_schema(con)
    agora = __import__("datetime").datetime.now().isoformat(timespec="seconds")

    pastas = sorted(p for p in ACERVO.iterdir() if p.is_dir())
    if args.limite:
        pastas = pastas[:args.limite]

    por_papel: Counter = Counter()
    n_proc = n_com_agente = n_decisor = n_fiscal = 0
    lac_117 = lac_ordenador = alerta_segregacao = 0
    nomes_por_papel: dict[str, Counter] = {}

    for i, pasta in enumerate(pastas, 1):
        docs = _textos(pasta)
        if not docs:
            continue
        n_proc += 1
        ficha = montar_ficha(pasta.name, docs)
        if ficha.agentes:
            n_com_agente += 1
        if any(a.papel in PAPEIS_DECISORIOS for a in ficha.agentes):
            n_decisor += 1
        if any(a.papel in PAPEIS_FISCALIZACAO for a in ficha.agentes):
            n_fiscal += 1
        for a in ficha.agentes:
            por_papel[a.papel] += 1
            # ranking entre processos normaliza o nome: o mesmo servidor aparece em CAIXA ALTA
            # no bloco de assinatura e capitalizado no rótulo — sem isso ele conta duas vezes.
            nomes_por_papel.setdefault(a.papel, Counter())[a.nome.title()] += 1
        for lac in ficha.lacunas:
            if "117" in lac:
                lac_117 += 1
            else:
                lac_ordenador += 1
        alerta_segregacao += len(ficha.alertas)

        if con is not None:
            con.executemany(
                "INSERT OR REPLACE INTO agente_processo VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(ficha.processo, a.nome, a.papel, a.id_funcional, a.matricula, a.cargo,
                  a.origem, a.documento, a.contexto[:600], agora) for a in ficha.agentes])
            con.executemany(
                "INSERT OR REPLACE INTO agente_lacuna VALUES (?,?,?,?)",
                [(ficha.processo, "art117_sem_fiscal" if "117" in l else "sem_ordenador",
                  l, agora) for l in ficha.lacunas]
                + [(ficha.processo, "segregacao_funcoes", a, agora) for a in ficha.alertas])
            if i % 100 == 0:
                con.commit()
        if i % 200 == 0:
            print(f"  ... {i}/{len(pastas)}", flush=True)

    if con is not None:
        con.commit()
        con.close()

    print(f"\nprocessos com texto : {n_proc}")
    print(f"com algum agente    : {n_com_agente} ({n_com_agente*100//max(1,n_proc)}%)")
    print(f"com decisor (ordenador/homologador): {n_decisor}")
    print(f"com fiscalizador                  : {n_fiscal}")
    print(f"\nagentes por papel: {dict(por_papel.most_common())}")
    print(f"\nLACUNA art. 117 (execução paga sem fiscal designado): {lac_117}")
    print(f"LACUNA sem ordenador identificado                   : {lac_ordenador}")
    print(f"ALERTA segregação de funções                        : {alerta_segregacao}")
    for papel in ("ordenador_despesa", "fiscal_contrato", "gestor_contrato"):
        top = (nomes_por_papel.get(papel) or Counter()).most_common(5)
        if top:
            print(f"\ntop {papel}: " + " · ".join(f"{n} ({c})" for n, c in top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
