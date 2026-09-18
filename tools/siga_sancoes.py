#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""siga_sancoes — o registro ESTADUAL de sanções do Portal SIGA (compras.rj.gov.br), inteiro, sem API.

Descoberto em 12/09/2026: `POST /Portal-Siga/Sancao/paginate.action` (DataTables) devolve TODAS as sanções
aplicadas por órgãos do Estado e por decisões judiciais (improbidade, art. 12 Lei 8.429) — 3.026 linhas:
nome, CPF/CNPJ, enquadramento legal, data de efetivação, órgão apenador, status (Vigente/Decorrido/Multado).
O CEIS/CNEP federal não traz as sanções estaduais que não foram comunicadas. Materializa `siga_sancoes` e cruza
com favorecidos do SIAFE, contratos TCE-RJ e fornecedores de TAC.

Uso: PYTHONPATH=. .venv/bin/python -m tools.siga_sancoes   (semanal)
"""
from __future__ import annotations

import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

_REPO = Path(__file__).resolve().parents[1]
DB = _REPO / "data" / "compliance.db"
URL = "https://www.compras.rj.gov.br/Portal-Siga/Sancao/paginate.action"
UA = {"User-Agent": "Mozilla/5.0 (JFN fiscalizacao)"}


def parse_linha(row: list) -> dict:
    r = [x if x is not None else "" for x in row] + [""] * 10
    doc = re.sub(r"\D", "", str(r[1]))
    return {"id_sancao": str(r[6]).strip(), "nome": str(r[0]).strip(), "doc": doc, "tipo_doc": "cnpj" if len(doc) == 14 else ("cpf" if len(doc) == 11 else "?"),
            "enquadramento": str(r[2]).strip(), "data_efetivacao": str(r[3]).strip(), "orgao_apenador": str(r[4]).strip(), "status": str(r[5]).strip()}


def baixar(por_pagina: int = 200, max_paginas: int = 100) -> list[dict]:
    out, start = [], 0
    with httpx.Client(headers=UA, follow_redirects=True) as c:
        for _ in range(max_paginas):
            r = c.post(URL, data={"draw": 1, "start": start, "length": por_pagina, "orderColumn": 0, "orderDirection": "asc",
                                  "cpfCnpj": "", "nomeRazaoSocial": "", "idEnquadramento": "", "idStatusSancao": "", "nomeUnidade": ""}, timeout=120)
            r.raise_for_status()
            d = r.json()
            rows = d.get("data") or []
            out.extend(parse_linha(x) for x in rows if isinstance(x, list))
            start += por_pagina
            if not rows or start >= int(d.get("recordsTotal") or 0):
                break
            time.sleep(0.5)
    return out


def materializar(itens: list[dict] | None = None) -> dict:
    itens = itens if itens is not None else baixar()
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with con:
        con.execute("DROP TABLE IF EXISTS siga_sancoes_novo")
        con.execute("CREATE TABLE siga_sancoes_novo (id_sancao TEXT, nome TEXT, doc TEXT, tipo_doc TEXT, enquadramento TEXT, "
                    "data_efetivacao TEXT, orgao_apenador TEXT, status TEXT, visto_em TEXT)")
        con.executemany("INSERT INTO siga_sancoes_novo VALUES (?,?,?,?,?,?,?,?,?)",
                        [(i["id_sancao"], i["nome"], i["doc"], i["tipo_doc"], i["enquadramento"], i["data_efetivacao"], i["orgao_apenador"], i["status"], agora) for i in itens])
        con.executescript("DROP TABLE IF EXISTS siga_sancoes; ALTER TABLE siga_sancoes_novo RENAME TO siga_sancoes; "
                          "CREATE INDEX IF NOT EXISTS ix_siga_sanc_doc ON siga_sancoes(doc);")
    cruz = {}
    try:
        cruz["favorecidos_vigentes"] = con.execute(
            "SELECT count(DISTINCT s.doc), round(sum(f.total_pago),2) FROM siga_sancoes s JOIN favorecido_resumo f ON f.favorecido_cpf=s.doc "
            "WHERE s.status='Vigente'").fetchone()
        cruz["tac_vigentes"] = con.execute(
            "SELECT count(DISTINCT s.doc) FROM siga_sancoes s JOIN doerj_tac_sinal t ON t.cnpj=s.doc WHERE s.status='Vigente'").fetchone()[0]
    except sqlite3.OperationalError:
        pass
    con.close()
    return {"sancoes": len(itens), "vigentes": sum(1 for i in itens if i["status"] == "Vigente"), **cruz}


def main() -> int:
    r = materializar()
    print(f"[siga-sancoes] {r['sancoes']} sanções ({r['vigentes']} vigentes) | favorecidos com sanção VIGENTE: {r.get('favorecidos_vigentes')} | fornecedores de TAC: {r.get('tac_vigentes')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
