#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aplica audit analytics (Benford na base + RSF/round/outlier/SSD no contrato) à MGS-ITERJ."""
import sqlite3
import sys
sys.path.insert(0, "/home/ubuntu/JFN")
from compliance_agent import auditoria_analitica as A

c = sqlite3.connect("/home/ubuntu/JFN/data/compliance.db").cursor()
br = lambda v: f"R$ {v:,.2f}"

todos = [r[0] for r in c.execute("SELECT valor FROM ob_orcamentaria_siafe WHERE valor>0")]
print(f"=== BENFORD — 1º dígito (base SIAFE, N={len(todos)}) ===")
b = A.benford_1d(todos)
if b.get("ok"):
    print(f"  MAD = {b['mad']}  →  faixa Nigrini: {b['faixa'].upper()}")
    print(f"  3 dígitos com maior desvio: {b['picos']}")
    print("  obs/esp (1-4): " + "  ".join(f"{d}:{b['observado'][d]}/{b['esperado'][d]}" for d in range(1, 5)))
else:
    print("  " + b.get("motivo", "?"))

obs = [dict(numero_ob=n, favorecido_cpf="19088605000104", valor=v, data_emissao=de, competencia=cp)
       for n, v, de, cp in c.execute(
       "SELECT numero_ob,valor,data_emissao,competencia FROM ob_orcamentaria_siafe "
       "WHERE ug_emitente='133100' AND credor='19088605000104'")]
print(f"\n=== CONTRATO 005/2021 MGS-ITERJ (N={len(obs)}) ===")
rsf = A.rsf(obs, chave="favorecido_cpf")
print("  RSF (>=10x, fora de escala):", rsf or "nenhum (escala saudável)")
print("  round-number:", A.round_number([o["valor"] for o in obs]))
outs = A.outliers_mod_z(obs)
print("  outliers (mod-z>3.5):", [(x["ob"], br(x["valor"]), x["mod_z"]) for x in outs] or "nenhum")
s = A.ssd(obs)
print(f"  SSD (mesmo CNPJ+valor, OBs distintas): {len(s)} grupos")
for x in s[:8]:
    print(f"     {br(x['valor'])} ×{x['n_obs']}: {x['docs']}")
