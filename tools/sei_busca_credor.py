#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fila de BUSCA NO SEI do processo de pagamento de um credor, para as competências sem processo.

Por que existe (12/11/2026): ~930 competências do resolvedor de duplicidade seguem INDETERMINADAS porque a OB
veio sem processo — 2021–2022 sobretudo (SIAFE 1 desativado em 10/11; contratos do TCE-RJ só de 2023). O SEI
tem os processos de pagamento; a pesquisa de texto completo (`tools/sei_busca_mgs.py`, documentos considerados)
acha os processos que citam o CNPJ do credor no período.

Filtro que segura a busca larga (lição de 21/06: CNPJ em texto pega processo que só MENCIONA a empresa):
  · só processo cujo TIPO diz "pagamento";
  · só processo cujo prefixo de unidade SEI (6 dígitos) a UG JÁ USA em OB com processo (aprendido do SIAFE).
O que sobra vai para `sei_busca_credor` (candidatos) e para `sei_fila_captura` (o sweep captura). O resolvedor
decide: candidato ÚNICO vira o processo; vários → vale o que tiver NF com o valor da OB.

Fila persistente, lote pequeno, sob o `browser_lock` do SEI (o mesmo do sweep). Repete só o que deu
`nao_parseei`/erro, depois de 3 dias.

    PYTHONPATH=. .venv/bin/python tools/sei_busca_credor.py [--lote 6] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from tools.resolver_duplicidade_nf import tag_processo  # noqa: E402

DB = REPO / "data" / "compliance.db"
_DDL = """CREATE TABLE IF NOT EXISTS sei_busca_credor (
    cnpj TEXT, ug TEXT, ano INTEGER, estado TEXT, n_total INTEGER, candidatos_json TEXT, buscado_em TEXT,
    PRIMARY KEY (cnpj, ug, ano))"""
_RETENTAR_DIAS = 3


def cnpj_fmt(c: str) -> str:
    d = re.sub(r"\D", "", c or "")
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if len(d) == 14 else d


def prefixos_por_ug(c) -> dict[str, set[str]]:
    """UG → prefixos de unidade SEI (6 dígitos) que ela já usou em OB com processo (≥ 3 OBs, para não aprender
    ruído de digitação)."""
    cont: dict[str, Counter] = defaultdict(Counter)
    for ug, proc in c.execute("SELECT ug_emitente, processo FROM ob_orcamentaria_siafe WHERE processo LIKE '%/%/%'"):
        t = tag_processo(proc)
        if t:
            cont[str(ug)][t[:6]] += 1
    return {ug: {p for p, n in v.items() if n >= 3} for ug, v in cont.items()}


def filtrar(todos: dict[str, str], prefixos: set[str]) -> list[str]:
    """Do resultado da busca, só os processos de PAGAMENTO de unidade que a UG usa."""
    out = []
    for num, tipo in (todos or {}).items():
        t = tag_processo(num)
        if t and t[:6] in prefixos and re.search(r"pagament", tipo or "", re.I):
            out.append("SEI-" + t.replace("_", "/"))
    return sorted(set(out))


def chaves(c) -> list[tuple[str, str, int]]:
    """(cnpj, ug, ano) das competências INDETERMINADAS por falta de processo, mais competências primeiro."""
    cont = Counter()
    for cnpj, ug, comp in c.execute("SELECT cnpj, ug, competencia FROM resolucao_duplicidade "
                                    "WHERE veredito='INDETERMINADO' AND motivo LIKE '%sem processo SEI%'"):
        if comp[-4:].isdigit():
            cont[(cnpj, str(ug), int(comp[-4:]))] += 1
    return [k for k, _ in cont.most_common()]


def pendentes(c, todas: list[tuple]) -> list[tuple]:
    feitos = {}
    try:
        for cnpj, ug, ano, estado, em in c.execute("SELECT cnpj, ug, ano, estado, buscado_em FROM sei_busca_credor"):
            feitos[(cnpj, ug, ano)] = (estado, em)
    except sqlite3.OperationalError:
        return todas
    limite = (datetime.now() - timedelta(days=_RETENTAR_DIAS)).isoformat(timespec="seconds")
    return [k for k in todas if k not in feitos
            or (feitos[k][0] not in ("com_resultado", "sem_resultado") and (feitos[k][1] or "") < limite)]


def buscar(cnpj: str, ano: int) -> dict:
    env = dict(os.environ, SEI_BUSCA_PAGINAS="10")
    r = subprocess.run([sys.executable, str(REPO / "tools" / "sei_busca_mgs.py"), cnpj_fmt(cnpj),
                        f"--de=01/01/{ano}", f"--ate=31/12/{ano + 1}"],
                       capture_output=True, text=True, timeout=900, env=env, cwd=REPO)
    out = r.stdout.strip()
    i = out.find("{")
    try:
        return json.loads(out[i:]) if i >= 0 else {"ok": False, "erro": (r.stderr or "")[-200:]}
    except ValueError:
        return {"ok": False, "erro": f"saída sem JSON (rc={r.returncode})"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lote", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    pref = prefixos_por_ug(ro)
    fila = pendentes(ro, chaves(ro))
    ro.close()
    print(f"[{time.strftime('%F %T')}] {len(fila)} chave(s) pendentes; lote {a.lote}", flush=True)
    if a.dry_run:
        for k in fila[: a.lote]:
            print("  ", k, sorted(pref.get(k[1], set())))
        return 0
    from compliance_agent.recursos import browser_lock
    for cnpj, ug, ano in fila[: a.lote]:
        if not pref.get(ug):
            estado, cands, n = "sem_prefixo_ug", [], 0
        else:
            with browser_lock(espera_max=1800):
                d = buscar(cnpj, ano)
            estado = d.get("estado") or ("erro" if not d.get("ok") else "nao_parseei")
            if d.get("vm_guard"):
                estado = "adiado_carga"
            n = d.get("n_total") or 0
            cands = filtrar(d.get("todos") or {}, pref[ug])
        c = sqlite3.connect(DB, timeout=120)
        try:
            c.execute(_DDL)
            c.execute("INSERT OR REPLACE INTO sei_busca_credor VALUES (?,?,?,?,?,?,?)",
                      (cnpj, ug, ano, estado, n, json.dumps(cands), datetime.now().isoformat(timespec="seconds")))
            for p in cands:
                c.execute("INSERT OR IGNORE INTO sei_fila_captura (numero_sei, sei_norm, motivo, total_pago, n_docs, "
                          "visto_em) VALUES (?,?,?,?,?,?)",
                          (p, re.sub(r"\D", "", p), f"busca_credor: {cnpj} UG {ug} {ano}", None, 0,
                           datetime.now().isoformat(timespec="seconds")))
            c.commit()
        finally:
            c.close()
        print(f"  {cnpj} UG {ug} {ano}: {estado} · {n} achado(s) · {len(cands)} candidato(s) {cands[:4]}", flush=True)
        if estado == "adiado_carga":
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
