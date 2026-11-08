# -*- coding: utf-8 -*-
"""Despesa de Exercícios Anteriores (DEA, elemento 92) recorrente ao mesmo fornecedor privado.

POR QUE EXISTE (04/11/2026). Na 1ª coleta de Nota de Empenho da UG 166100, todo "Passivo reconhecido
previamente" a fornecedor era DEA (339092/449092): R$ 20,25 mi em 448 NE — Bambina Oncos R$ 5,00 mi, Oncomed
R$ 3,38 mi, MGS CLEAN em 4 NE. DEA isolada é legal; DEA REPETIDA ao mesmo credor, em processos diferentes, é o
padrão de serviço prestado sem empenho prévio e regularizado depois (o mesmo dos indenizatórios/TAC da casa).

BASE (Planalto, conferido em 04/11/2026):
  • Lei 4.320/1964, art. 37 — "As despesas de exercícios encerrados, para as quais o orçamento respectivo
    consignava crédito próprio" (…) podem ser pagas à conta de dotação específica — exceção com requisitos;
  • art. 60 — "É vedada a realização de despesa sem prévio empenho."

FORÇA: forte = 3+ processos distintos com DEA ao mesmo credor na UG; medio = 2; fraco = 1 (legal se cumpriu o
art. 37 — conferir o reconhecimento no processo).

LIMITES. Indício: DEA pode decorrer de falta de crédito no fim do exercício, com contrato válido. Cobertura =
só UGs com NE coletada (`compliance_agent/siafe_documento.py`). Empenho não é pagamento.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

_SQL = ("SELECT numero, ug_emitente, ano_ne, data_emissao, credor, nome_credor, natureza, processo, valor "
        "FROM ne_siafe WHERE status='Contabilizado' AND valor>0 AND length(credor)=14 AND substr(natureza,5,2)='92'")


def dea_recorrente(db_path=None, estab_path=None) -> dict:
    con = sqlite3.connect(f"file:{db_path or _REPO / 'data' / 'compliance.db'}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        nes = con.execute(_SQL).fetchall()
        ugs = [r[0] for r in con.execute("SELECT DISTINCT ug_emitente FROM ne_siafe")]
    finally:
        con.close()
    est = sqlite3.connect(f"file:{estab_path or _REPO / 'data' / 'receita_estab.db'}?mode=ro", uri=True, timeout=30)
    nat = {}
    try:
        for b in {r["credor"][:8] for r in nes}:
            x = est.execute("SELECT natureza_cod FROM empresas WHERE cnpj_basico=?", (b,)).fetchone()
            nat[b] = str(x[0]) if x and x[0] else ""
    finally:
        est.close()
    grupos: dict[tuple, dict] = defaultdict(lambda: {"valor": 0.0, "nes": [], "processos": set()})
    for r in nes:
        n = nat.get(r["credor"][:8], "")
        if not n or n.startswith("1"):              # ente público fica fora
            continue
        g = grupos[(r["credor"], r["ug_emitente"])]
        g.update(credor=r["credor"], nome=r["nome_credor"], ug=r["ug_emitente"])
        g["valor"] += r["valor"]
        g["processos"].add(r["processo"] or r["numero"])
        g["nes"].append({"numero": r["numero"], "data": r["data_emissao"], "natureza": r["natureza"],
                         "processo": r["processo"], "valor": round(r["valor"], 2)})
    achados = []
    for g in grupos.values():
        k = len(g["processos"])
        achados.append({**g, "valor": round(g["valor"], 2), "n_processos": k, "processos": sorted(g["processos"]),
                        "n_ne": len(g["nes"]), "nes": sorted(g["nes"], key=lambda x: -x["valor"])[:10],
                        "forca": "forte" if k >= 3 else "medio" if k == 2 else "fraco"})
    ordem = {"forte": 0, "medio": 1, "fraco": 2}
    achados.sort(key=lambda a: (ordem[a["forca"]], -a["valor"]))
    return {"ok": True, "n": len(achados), "ugs_cobertas": sorted(ugs),
            "por_forca": {k: sum(a["forca"] == k for a in achados) for k in ordem},
            "nota": "Indício a verificar, não acusação: DEA é legal quando cumpre a Lei 4.320, art. 37; a recorrência "
                    "ao mesmo credor é o que pede conferir se havia empenho prévio (art. 60). Valor = empenhado, "
                    "não pago. Só UGs com Nota de Empenho coletada.",
            "achados": achados}
