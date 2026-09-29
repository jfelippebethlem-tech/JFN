#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GRUPO ECONÔMICO POR DOMÍNIO DE E-MAIL — quem administra as mesmas empresas?

Nasceu do caso ENGE PRAT (2026-08-16): o e-mail `heloisa@engeprat.com.br` está no cadastro da SÃO
VICENTE EMPREENDIMENTOS SPE e liga essa empresa a 11 outros CNPJs, cinco anotados como "sociedade em
conta de participação — quem aparece é o sócio ostensivo". A base já tinha a aresta; faltava a lente.

**O DOMÍNIO GENÉRICO É RUÍDO, E ELE DOMINA O TOPO.** Medido: `gmail.com` liga 622 CNPJs e sozinho
somaria R$ 705,5 mi. E-mail pessoal não é grupo econômico — quem usa Gmail não está administrando as
mesmas empresas, está apenas usando Gmail. Sem essa guarda a lente vira gerador de coincidência.

O que resta são domínios CORPORATIVOS, e aí o sinal é forte: o mesmo domínio no cadastro da Receita
de CNPJs distintos indica administração comum — contabilidade, procuração, gestão. **Não prova
controle societário**, e é isso que o torna útil como porta de entrada para exame, não como conclusão.

RESSALVAS QUE INTEGRAM O RESULTADO:
  · a aresta é ADMINISTRATIVA (quem responde pelo cadastro), não societária;
  · escritório de contabilidade legitimamente atende dezenas de empresas sem relação entre si —
    por isso a lente ordena por dinheiro recebido, não por tamanho do grupo;
  · só OB `status='Contabilizado'`.

Uso:
    .venv/bin/python tools/grupo_por_dominio.py
    .venv/bin/python tools/grupo_por_dominio.py --min-cnpj 5 --limite 30
"""
from __future__ import annotations

import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compliance_agent.reporting.intel_base import moeda

DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"

# Provedores públicos: presença comum NÃO indica grupo. `gmail.com` sozinho liga 622 CNPJs.
GENERICOS = {
    "gmail.com", "hotmail.com", "outlook.com", "yahoo.com.br", "yahoo.com", "bol.com.br",
    "uol.com.br", "terra.com.br", "ig.com.br", "globo.com", "live.com", "msn.com",
    "outlook.com.br", "hotmail.com.br", "icloud.com", "me.com", "protonmail.com",
}


def grupos_por_dominio(con: sqlite3.Connection, min_cnpj: int = 2) -> list[dict]:
    """Domínio corporativo -> CNPJs que o declaram, com o quanto receberam do Estado."""
    grupos: dict = collections.defaultdict(set)
    for (desc,) in con.execute(
            "SELECT descricao FROM relacionamentos WHERE tipo='mesmo_contador'"):
        s = str(desc)
        m = re.search(r"e-mail\s+(\S+)", s)
        if not m:
            continue
        dom = m.group(1).split("@")[-1].lower().strip("·, ")
        if dom in GENERICOS or "." not in dom:
            continue
        for cn in re.findall(r"\b(\d{14})\b", s):
            grupos[dom].add(cn)
    grupos = {d: c for d, c in grupos.items() if len(c) >= min_cnpj}
    if not grupos:
        return []

    todos = set().union(*grupos.values())
    # UMA varredura das OBs — uma query por CNPJ estoura o tempo (erro cometido e corrigido).
    pago: dict = collections.defaultdict(float)
    obs: dict = collections.Counter()
    for credor, valor in con.execute(
            "SELECT credor, valor FROM ob_orcamentaria_siafe WHERE status='Contabilizado'"):
        d = re.sub(r"\D", "", str(credor))
        if d in todos:
            pago[d] += (valor or 0)
            obs[d] += 1

    nomes = {}
    for b, rs in con.execute("SELECT cnpj_basico, razao_social FROM empresas_cadastro"):
        nomes[str(b).zfill(8)] = rs

    saida = []
    for dom, cns in grupos.items():
        total = sum(pago.get(x, 0) for x in cns)
        pagos = [(pago[x], x) for x in cns if x in pago]
        pagos.sort(reverse=True)
        saida.append({
            "dominio": dom, "cnpjs": len(cns), "com_pagamento": len(pagos), "pago": total,
            "obs": sum(obs.get(x, 0) for x in cns),
            "maior": (nomes.get(pagos[0][1][:8], pagos[0][1]) if pagos else "—"),
        })
    saida.sort(key=lambda x: -x["pago"])
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--min-cnpj", type=int, default=2, help="mínimo de CNPJs no domínio")
    ap.add_argument("--limite", type=int, default=20)
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    linhas = grupos_por_dominio(con, min_cnpj=a.min_cnpj)
    print(f"grupos por domínio corporativo (>= {a.min_cnpj} CNPJs): {len(linhas)}")
    print(f"total recebido do Estado: R$ {moeda(sum(x['pago'] for x in linhas))}")
    print("\nARESTA ADMINISTRATIVA, não societária: mesmo domínio no cadastro da Receita indica "
          "administração\ncomum (contabilidade, procuração) — não prova controle. Provedores "
          "públicos ficam de fora:\n`gmail.com` sozinho ligaria 622 CNPJs e R$ 705,5 mi de ruído.\n")
    print(f"{'CNPJs':>6} {'pagos':>6} {'total pago':>18}  domínio · maior recebedor")
    for x in linhas[:a.limite]:
        print(f"{x['cnpjs']:6d} {x['com_pagamento']:6d} R$ {moeda(x['pago']):>15}  "
              f"{x['dominio'][:26]:26} · {x['maior'][:28]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
