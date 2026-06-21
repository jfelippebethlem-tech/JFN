#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PERÍCIA — reconciliação OB-a-OB contra a base DOCUMENTAL (ASSCONT, contrato 005/2021,
proc SEI-330020/000762/2021, doc SEI 130341565, p.11-13). Verifica independentemente o
crédito R$56.044,28. Saída .txt (sem PDF pesado). Decimal p/ centavos exatos."""
import sqlite3
from decimal import Decimal as D, ROUND_HALF_UP
from datetime import date
from pathlib import Path

REPO = Path("/home/ubuntu/JFN")
con = sqlite3.connect(REPO / "data/compliance.db"); cur = con.cursor()
UG, CNPJ = "133100", "19088605000104"

def brl(v): return f"{D(v).quantize(D('0.01')):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# ── BASE DOCUMENTAL (gross/NF — contrato 762/2021 p.11-13, citada) ──
VALOR_MENSAL = {  # vigência por CCT (valor NF mensal bruto)
    "inicial": D("90419.34"), "cct2022": D("98276.62"), "cct2023": D("103988.53"),
    "cct2024": D("109687.73"), "cct2025": D("118441.47"), "glosado2025": D("113184.14"),
}
CCT_PCT = {"2022": "9,91%", "2023": "6,01%", "2024": "6,20%", "2025": "7,50%"}
# retroativos documentados (apostilamentos) e glosas
RETROATIVOS = {
    "Mar-Jun/22 (9,91%)": D("31429.12"), "Mar-Jun/23 (6,01%)": D("22847.64"),
    "Mar-Mai/24 (6,20%)": D("17097.60"), "Mar-Jun/25 (7,50%)": D("35014.96"),
}
# ciclos Nov-a-Nov e total pago documentado (gross)
CICLOS = [
    ("01/12/2021-20/11/2022", D("1179319.44")), ("21/11/2022-20/11/2023", D("1230726.63")),
    ("21/11/2023-20/11/2024", D("1299155.16")), ("21/11/2024-19/11/2025", D("1354764.13")),
]

def comp_to_date(c):
    c = (c or "").strip()
    for fmt in ("%d/%m/%Y", "%m/%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(c, fmt).date().replace(day=1)
        except ValueError:
            pass
    return None

def ciclo_de(d):  # qual ciclo Nov-Nov
    if not d: return "?"
    y = d.year
    ref = date(y, 11, 21)
    ini = date(y-1, 11, 21) if d < ref else date(y, 11, 21)
    return f"{ini.strftime('%d/%m/%Y')}-{(date(ini.year+1,11,20)).strftime('%d/%m/%Y')}"

obs = cur.execute(f"""SELECT exercicio,numero_ob,competencia,valor,COALESCE(re,''),COALESCE(pd,'')
    FROM ob_orcamentaria_siafe WHERE ug_emitente='{UG}' AND credor='{CNPJ}' ORDER BY competencia,numero_ob""").fetchall()

L = []
L.append("="*92)
L.append("PERÍCIA CONTÁBIL — RECONCILIAÇÃO OB-a-OB vs. BASE DOCUMENTAL")
L.append("Contrato 005/2021 · ITERJ (UG 133100) × MGS Clean (CNPJ 19.088.605/0001-04)")
L.append("Base: ASSCONT, proc SEI-330020/000762/2021, doc SEI 130341565 (p.11-13), assinado 22/04/2026")
L.append("Índice de reajuste = CCT do setor de asseio/conservação:  " + " · ".join(f"{k}:{v}" for k,v in CCT_PCT.items()))
L.append("Contrato Nov-a-Nov (não ano-civil). Valor mensal NF (bruto): " + " → ".join(f"R$ {brl(v)}" for v in
         [VALOR_MENSAL['inicial'],VALOR_MENSAL['cct2022'],VALOR_MENSAL['cct2023'],VALOR_MENSAL['cct2024'],VALOR_MENSAL['cct2025']]))
L.append("="*92)

# agrupa OBs por ciclo
from collections import defaultdict
por_ciclo = defaultdict(list)
total_obs = D("0")
for ex,ob,comp,val,re_,pd in obs:
    d = comp_to_date(comp); cic = ciclo_de(d)
    por_ciclo[cic].append((ob,comp,D(str(val)),re_,pd)); total_obs += D(str(val))

L.append(f"\nTOTAL OBs (SIAFE direto, líquido pago): {len(obs)} OBs = R$ {brl(total_obs)}\n")
for cic in sorted(por_ciclo):
    itens = por_ciclo[cic]; soma = sum((x[2] for x in itens), D("0"))
    L.append(f"── Ciclo {cic} — {len(itens)} OBs — pago(líquido) R$ {brl(soma)} ──")
    for ob,comp,val,re_,pd in sorted(itens, key=lambda x: x[1] or ""):
        L.append(f"    {comp or '—':<11} {ob:<12} RE={re_:<12} PD={pd:<12} R$ {brl(val):>13}")
L.append("")

# ── VERIFICAÇÃO INDEPENDENTE DO CRÉDITO R$56.044,28 ──
L.append("="*92)
L.append("VERIFICAÇÃO INDEPENDENTE DO CRÉDITO (refazendo a aritmética do documento)")
dif_repac = (VALOR_MENSAL['cct2025'] - VALOR_MENSAL['cct2024'])
c1 = dif_repac * 4
dif_glosa = (VALOR_MENSAL['cct2025'] - VALOR_MENSAL['glosado2025'])
c2 = dif_glosa * 4
L.append(f"  (1) Retroativo repactuação Mar-Jun/25: (118.441,47 − 109.687,73) = R$ {brl(dif_repac)} × 4 = R$ {brl(c1)}")
L.append(f"  (2) Diferença NF glosada Nov/25-Fev/26: (118.441,47 − 113.184,14) = R$ {brl(dif_glosa)} × 4 = R$ {brl(c2)}")
L.append(f"  CRÉDITO TOTAL recalculado = R$ {brl(c1+c2)}   |   documento ASSCONT = R$ 56.044,28   →  "
         + ("✅ CONFERE" if (c1+c2)==D("56044.28") else f"⚠ DIVERGE ({brl(c1+c2)})"))
L.append("="*92)
L.append("\nRESSALVAS (honestidade): (a) OBs são LÍQUIDAS (pós-retenção); a base ASSCONT é BRUTA (NF) — o")
L.append("casamento fino exige as OBs de Retenção (INSS/ISS/IRRF) por competência. (b) Confirmação final de")
L.append("não-duplicidade por competência depende da NL (drill SIAFE 1 em construção) + NF (SEI execução).")
L.append("(c) Documento de reconciliação é do próprio órgão (derivado) — verificado contra OB primária aqui.")
L.append("Indício ≠ acusação · presunção de legitimidade · só a NF fecha.")

out = REPO / "reports/pericia_reconciliacao_mgs.txt"
out.write_text("\n".join(L), encoding="utf-8")
print("\n".join(L))
print(f"\n>>> salvo: {out}")
con.close()
