#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""resolver_cpf_socios — aplica o resolver MULTI-FONTE (favorecidos-PF + TSE + SEI) a TODOS os sócios
mascarados do QSA (`socios_fornecedor`) e grava o CPF completo resolvido na própria tabela.

Liga a resolução existente (`compliance_agent.resolucao_cpf.resolver_multi`) à DD/relatório: hoje os
~1k resolvidos só viviam em `socio_beneficio`; aqui o vínculo nome↔CPF passa a estar em `socios_fornecedor`
(consultável por CNPJ no relatório do fornecedor). Match 1:1 obrigatório (nome + 6 díg do meio = checksum);
ambíguo/sem corpus → NÃO resolve (INDISPONÍVEL, nunca chute). LGPD: CPF completo é uso INTERNO; produto mascara.

VM-safe: os 3 índices são carregados UMA vez (sem 1 full-scan por sócio); writer com busy_timeout+WAL (§8).
Uso: PYTHONPATH=. .venv/bin/python -m tools.resolver_cpf_socios [--forcar] [--limite N]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compliance_agent import resolucao_cpf as rc  # noqa: E402

_DB = Path("data") / "compliance.db"

_DDL = [
    "ALTER TABLE socios_fornecedor ADD COLUMN cpf_resolvido TEXT",
    "ALTER TABLE socios_fornecedor ADD COLUMN cpf_fonte TEXT",
    "ALTER TABLE socios_fornecedor ADD COLUMN cpf_confianca REAL",
    "ALTER TABLE socios_fornecedor ADD COLUMN cpf_resolvido_em TEXT",
    "ALTER TABLE socios_fornecedor ADD COLUMN socio_servidor INTEGER",  # fusão folha×QSA
    "ALTER TABLE socios_fornecedor ADD COLUMN cpf_pos3a9 TEXT",         # 7 díg conhecidos (pos.3-9)
]


def _garantir_colunas(con: sqlite3.Connection) -> None:
    cols = {c[1] for c in con.execute("PRAGMA table_info(socios_fornecedor)")}
    for ddl in _DDL:
        nome = ddl.split("ADD COLUMN ")[1].split()[0]
        if nome not in cols:
            con.execute(ddl)
    con.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--forcar", action="store_true", help="reprocessa mesmo quem já tem cpf_resolvido")
    ap.add_argument("--limite", type=int, default=0, help="processa no máx. N sócios (0 = todos)")
    a = ap.parse_args()

    con = sqlite3.connect(str(_DB), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.row_factory = sqlite3.Row
    _garantir_colunas(con)

    print("carregando índices (favorecidos-PF + TSE + SEI + folha)…", flush=True)
    pf_idx = rc.carregar_indice_favorecidos(_DB)
    tse_idx = rc.carregar_indice_tse(_DB)
    sei_idx = rc.carregar_indice_sei(_DB)
    folha_idx = rc.carregar_indice_folha(_DB)
    print(f"  índices: favorecidos={len(pf_idx)}  tse={len(tse_idx)}  sei={len(sei_idx)}  "
          f"folha={len(folha_idx)} nomes")

    cond = "" if a.forcar else " AND (cpf_resolvido IS NULL OR cpf_resolvido='') "
    lim = f" LIMIT {int(a.limite)}" if a.limite else ""
    alvos = con.execute(
        f"SELECT rowid, socio_nome, socio_doc FROM socios_fornecedor "
        f"WHERE socio_doc LIKE '%*%' {cond} ORDER BY rowid{lim}").fetchall()
    print(f"{len(alvos)} sócio(s) mascarado(s) a resolver.")

    resolvidos = servidores = 0
    fontes: dict[str, int] = {}
    agora = dt.datetime.now().isoformat(timespec="seconds")
    escrita = con.cursor()
    for i, r in enumerate(alvos, 1):
        res = rc.resolver_multi(r["socio_nome"], r["socio_doc"],
                                pf_idx=pf_idx, tse_idx=tse_idx, sei_idx=sei_idx)
        if res.get("resolvido"):
            escrita.execute(
                "UPDATE socios_fornecedor SET cpf_resolvido=?, cpf_fonte=?, cpf_confianca=?, "
                "cpf_resolvido_em=? WHERE rowid=?",
                (res["cpf"], res.get("fonte", ""), res.get("confianca", 0.0), agora, r["rowid"]))
            resolvidos += 1
            fontes[res.get("fonte", "?")] = fontes.get(res.get("fonte", "?"), 0) + 1
        # fusão de máscaras folha×QSA — sócio que também é servidor público (indício de conflito/laranja)
        fus = rc.fusao_folha_qsa(r["socio_nome"], r["socio_doc"], folha_idx)
        if fus.get("servidor"):
            escrita.execute(
                "UPDATE socios_fornecedor SET socio_servidor=1, cpf_pos3a9=? WHERE rowid=?",
                (fus.get("conhecidos_3a9", ""), r["rowid"]))
            servidores += 1
        if i % 5000 == 0:
            con.commit()
            print(f"  …{i}/{len(alvos)} (resolvidos={resolvidos} servidores={servidores})", flush=True)
    con.commit()
    print(f"\nFIM: resolvidos={resolvidos}/{len(alvos)} "
          f"({100*resolvidos/max(1,len(alvos)):.1f}%)  por fonte={fontes}")
    print(f"     servidores-sócios (fusão folha×QSA): {servidores}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
