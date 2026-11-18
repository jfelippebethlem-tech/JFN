#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Visita o site próprio dos fornecedores (domínio do e-mail da Receita) e guarda no cache de 30 dias.

Validador independente de sede (compliance_agent/fachada_validadores.py): o site cita o CNPJ, a razão,
o logradouro? Que redes sociais ele aponta? Os produtos interativos (Lex, dossiê, card C) só LEEM o
cache — quem visita é este sweep, educado: 1 requisição/s, 12 s de timeout, maior valor pago primeiro,
retomável (o cache pula quem já foi visitado), para com load alto.

Domínio usado por mais de 2 grupos empresariais entre os fornecedores é de escritório (Contabilizei,
Datecon, Holak…), não da empresa — fica de fora.

Uso:
  PYTHONPATH=. nice -n10 .venv/bin/python -m tools.fachada_validar_site [--limite 200] [--max-min 20]
"""
from __future__ import annotations

import argparse
import collections
import os
import sqlite3
import sys
import time
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAIZ))

from compliance_agent.cruzamentos_intel import _ob_paga  # noqa: E402
from compliance_agent.fachada_validadores import checar_site, dominio_corporativo, site_em_cache  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limite", type=int, default=200)
    ap.add_argument("--max-min", type=float, default=20.0)
    ap.add_argument("--load-teto", type=float, default=6.0)
    a = ap.parse_args()
    con = sqlite3.connect(f"file:{_RAIZ / 'data/compliance.db'}?mode=ro", uri=True, timeout=30)
    rf = sqlite3.connect(f"file:{_RAIZ / 'data/receita_estab.db'}?mode=ro", uri=True, timeout=30)
    credores = [r[0] for r in con.execute(
        f"SELECT credor FROM ob_orcamentaria_siafe WHERE {_ob_paga(con)} AND length(credor)=14 "
        "GROUP BY credor ORDER BY SUM(valor) DESC")]
    info, grupos_dom = {}, collections.defaultdict(set)
    for c in credores:
        e = rf.execute("SELECT correio_eletronico, tipo_logradouro, logradouro FROM estabelecimentos WHERE cnpj=?",
                       (c,)).fetchone()
        if not e or "@" not in (e[0] or ""):
            continue
        dom = e[0].rsplit("@", 1)[1].strip().lower()
        grupos_dom[dom].add(c[:8])
        m = rf.execute("SELECT razao_social FROM empresas WHERE cnpj_basico=?", (c[:8],)).fetchone()
        info[c] = (e[0], f"{e[1] or ''} {e[2] or ''}".strip(), (m or [""])[0] or "")
    t0, feitos, cont = time.time(), 0, collections.Counter()
    for c in credores:
        if c not in info:
            continue
        email, logradouro, razao = info[c]
        dom = dominio_corporativo(email, len(grupos_dom[email.rsplit("@", 1)[1].strip().lower()]))
        if not dom or site_em_cache(dom, c):
            continue
        if feitos >= a.limite or (time.time() - t0) / 60 > a.max_min:
            break
        if os.getloadavg()[0] > a.load_teto:
            print(f"[site] load {os.getloadavg()[0]:.1f} > {a.load_teto} — parando (retomável)")
            break
        r = checar_site(dom, c, razao, logradouro)
        cont[r["estado"]] += 1
        feitos += 1
    print(f"[site] visitados {feitos} em {time.time() - t0:.0f}s: {dict(cont)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
