# -*- coding: utf-8 -*-
"""
enriquecer_socios_ob — busca e indexa, POR OB, os sócios/diretores/administradores dos CNPJs
credores das nossas Ordens Bancárias. Roda em BACKGROUND, idempotente.

Fonte: BrasilAPI (campo qsa) via compliance_agent.rede_societaria.ingerir (grava em socios_fornecedor,
keyed por CNPJ → join com OB.credor/favorecido dá os sócios por OB). Pula CNPJs já feitos.

CNPJs = credores de 14 dígitos em ob_orcamentaria_siafe.credor + favorecido_cpf (14d) de ordens_bancarias.
Uso: PYTHONPATH=. .venv/bin/python -m tools.enriquecer_socios_ob   (rodar com run_in_background)
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"


def _cnpjs_dos_obs() -> list[str]:
    con = sqlite3.connect(str(_DB))
    try:
        cnpjs = set()
        # credor das OB Orçamentárias (SIAFE) — só os que são CNPJ (14 dígitos numéricos)
        for (c,) in con.execute("SELECT DISTINCT credor FROM ob_orcamentaria_siafe WHERE credor IS NOT NULL"):
            d = "".join(ch for ch in str(c) if ch.isdigit())
            if len(d) == 14:
                cnpjs.add(d)
        # favorecido_cpf das ordens_bancarias (TFE) — pega os de 14 dígitos (CNPJ)
        try:
            for (c,) in con.execute("SELECT DISTINCT favorecido_cpf FROM ordens_bancarias WHERE favorecido_cpf IS NOT NULL"):
                d = "".join(ch for ch in str(c) if ch.isdigit())
                if len(d) == 14:
                    cnpjs.add(d)
        except Exception:
            pass
        return sorted(cnpjs)
    finally:
        con.close()


async def main():
    from compliance_agent import rede_societaria
    todos = _cnpjs_dos_obs()
    con = sqlite3.connect(str(_DB))
    ja = {r[0] for r in con.execute("SELECT DISTINCT cnpj FROM socios_fornecedor")}
    con.close()
    pend = [c for c in todos if c not in ja]
    print(f"[socios_ob] CNPJs credores nas OBs: {len(todos)} | já feitos: {len(todos)-len(pend)} | pendentes: {len(pend)}", flush=True)
    if not pend:
        print("[socios_ob] nada pendente — tudo indexado.", flush=True)
        return
    # processa em blocos, com jitter (BrasilAPI tem rate-limit); idempotente — pode rerodar
    BLOCO = 50
    t0 = time.time()
    for i in range(0, len(pend), BLOCO):
        lote = pend[i:i + BLOCO]
        res = await rede_societaria.ingerir(lote, delay=1.2)
        feitos = i + len(lote)
        print(f"[socios_ob] {feitos}/{len(pend)} | bloco: {res} | {time.time()-t0:.0f}s", flush=True)
    print(f"[socios_ob] CONCLUÍDO: {len(pend)} CNPJs processados em {time.time()-t0:.0f}s", flush=True)
    print("[socios_ob] stats:", rede_societaria.stats(), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
