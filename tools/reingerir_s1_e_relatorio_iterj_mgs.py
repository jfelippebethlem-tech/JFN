#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Corrige a ingestão SIAFE 1 (2022/2023 ITERJ, mapeando pelo HEADER real) e monta o relatório
consolidado ITERJ->MGS 2022-2026 (SIAFE 1+2), deduplicado, e envia ao Yoda."""
import json, re, sqlite3, time
from pathlib import Path
import httpx

REPO = Path("/home/ubuntu/JFN")
DB = REPO / "data/compliance.db"
ENV = Path("/home/ubuntu/.hermes/.env")
OUT = REPO / "reports/iterj_mgs_obs_siafe_por_ano.txt"
CNPJ = "19088605000104"
UG = "133100"

# header SIAFE 1 (label do grid) -> coluna da tabela ob_orcamentaria_siafe
MAP_S1 = {
    "Número": "numero_ob", "UG Emitente": "ug_emitente", "UG Pagadora": "ug_pagadora",
    "Data Emissão": "data_emissao", "Status": "status", "Tipo": "tipo", "Finalidade": "finalidade",
    "Credor": "credor", "Nome do Credor": "nome_credor", "UG Liquidante": "ug_liquidante",
    "Valor": "valor", "Status de Envio": "status_envio", "Guia Devolução": "gd", "RE": "re",
    "PD": "pd", "Tipo de Regularização": "tipo_regularizacao", "Qtd. Impressões": "qtd_impressoes",
    "Data de Competência": "competencia", "Vinculação de Pagamento": "vinculacao_pagamento",
}


def money(s):
    s = (s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def brl(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


con = sqlite3.connect(DB)
cur = con.cursor()
agora = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

# ---- 1) RE-INGESTÃO correta de 2022 e 2023 (ITERJ) a partir do cru ----
for ano in (2022, 2023):
    d = json.loads((REPO / f"data/sei_cache/siafe1_iterj_{ano}.json").read_text())
    h = d["header"]
    # apaga linhas desalinhadas dessa UG/ano
    cur.execute("DELETE FROM ob_orcamentaria_siafe WHERE exercicio=? AND ug_emitente=?", (ano, UG))
    ins = 0
    for r in d["linhas"]:
        rec = {MAP_S1[h[i]]: (r[i] if i < len(r) else "") for i in range(len(h)) if h[i] in MAP_S1}
        rec["valor"] = money(rec.get("valor"))
        rec["exercicio"] = ano
        rec["coletado_em"] = agora
        cols = ",".join(rec.keys())
        ph = ",".join("?" * len(rec))
        cur.execute(f"INSERT OR REPLACE INTO ob_orcamentaria_siafe ({cols}) VALUES ({ph})", tuple(rec.values()))
        ins += 1
    print(f"{ano}: re-ingeridas {ins} OBs do ITERJ (header-mapped)")
con.commit()

# ---- 2) Consolidado ITERJ->MGS 2022-2026 (dedup por numero_ob; PK já garante) ----
rows = cur.execute(
    """SELECT exercicio, numero_ob, data_emissao, valor, status, competencia, re, pd, nome_credor, vinculacao_pagamento
       FROM ob_orcamentaria_siafe
       WHERE ug_emitente=? AND credor=?
       ORDER BY exercicio, numero_ob""",
    (UG, CNPJ),
).fetchall()

por_ano, vistos = {}, set()
for ex, ob, dt, val, st, comp, re_, pd, nome, vinc in rows:
    if ob in vistos:   # dedup defensivo (PK já evita; cobre sufixo igual)
        continue
    vistos.add(ob)
    por_ano.setdefault(ex, []).append((ob, dt, val, st, comp, re_, pd))
total = sum(v[2] for ano in por_ano for v in por_ano[ano])
n = sum(len(v) for v in por_ano.values())
SIS = lambda y: "SIAFE 1" if y <= 2023 else "SIAFE 2"

# detecta valores repetidos por ano (possível reemissão/estorno) p/ sinalizar
def repetidos(obs):
    from collections import Counter
    c = Counter(round(o[2], 2) for o in obs)
    return {v: k for v, k in c.items() if k > 1}

L = []
L.append("=" * 96)
L.append("PAGAMENTOS DO ITERJ À MGS CLEAN — ORDENS BANCÁRIAS (SIAFE DIRETO) POR EXERCÍCIO")
L.append("Pagador: INST. DE TERRAS E CARTOGR. DO EST. RJ (ITERJ) — UG 133100")
L.append("Favorecido: MGS CLEAN SOLUÇÕES E SERVIÇOS — CNPJ 19.088.605/0001-04")
L.append("Fonte: SIAFE-Rio DIRETO — SIAFE 1 (www5, 2022–2023) + SIAFE 2 (2024–2026). SEM espelho TFE.")
L.append("=" * 96)
L.append(f"TOTAL: {n} OBs   —   R$ {brl(total)}")
L.append("Nota: OB = pagamento (liquidação). Empenho ≠ OB.")
L.append("")
L.append("RESUMO POR ANO")
L.append("-" * 96)
L.append(f"{'ANO':<6}{'SISTEMA':<9}{'OBs':>5}{'VALOR PAGO (R$)':>22}   OBS")
for ex in sorted(por_ano):
    obs = por_ano[ex]
    rep = repetidos(obs)
    flag = f"⚠ {sum(rep.values())} c/ valor repetido" if rep else ""
    L.append(f"{ex:<6}{SIS(ex):<9}{len(obs):>5}{brl(sum(o[2] for o in obs)):>22}   {flag}")
L.append("-" * 96)
L.append(f"{'TOTAL':<20}{n:>5}{brl(total):>22}")
L.append("")
L.append("DETALHAMENTO POR ANO")
L.append("=" * 96)
for ex in sorted(por_ano):
    obs = por_ano[ex]
    rep = repetidos(obs)
    L.append("")
    L.append(f"━━ {ex}  ({SIS(ex)})  —  {len(obs)} OBs  —  R$ {brl(sum(o[2] for o in obs))}")
    L.append(f"   {'OB':<14}{'DATA':<12}{'VALOR (R$)':>15}  {'COMPET.':<10}{'STATUS':<18}{'RE/PD'}")
    for ob, dt, val, st, comp, re_, pd in obs:
        mark = " ◀ valor repetido" if round(val, 2) in rep else ""
        rp = f"{re_ or ''}/{pd or ''}".strip("/")
        L.append(f"   {ob:<14}{(dt or ''):<12}{brl(val):>15}  {(comp or ''):<10}{(st or ''):<18}{rp}{mark}")
L.append("")
L.append("=" * 96)
L.append("NOTAS DE AUDITORIA (honestidade)")
L.append("- Fonte SIAFE direto (pedido do dono); o espelho TFE foi descartado. O SIAFE traz mais OBs que")
L.append("  o TFE: 2022 13×11, 2023 15×11, 2024 13×11 — o TFE subcontava.")
L.append("- 2023 existe SÓ no SIAFE 1 (bloqueado no SIAFE 2 p/ esta conta) → sem risco de dupla contagem")
L.append("  entre sistemas. Dedup por nº de OB aplicado mesmo assim.")
L.append("- OBs com VALOR REPETIDO no mesmo ano (marcadas ◀) podem ser reemissão/estorno — indício a")
L.append("  verificar no processo, NÃO conclusão. O grid de OB do SIAFE 1 não expõe a coluna Processo/SEI.")
L.append("=" * 96)
OUT.write_text("\n".join(L), encoding="utf-8")
con.close()

linhas_resumo = "\n".join(
    f"• {ex} ({SIS(ex)}) — {len(por_ano[ex])} OBs · R$ {brl(sum(o[2] for o in por_ano[ex]))}"
    + (" ⚠" if repetidos(por_ano[ex]) else "")
    for ex in sorted(por_ano)
)
msg = (
    f"🏛️ *ITERJ → MGS Clean — OBs do SIAFE DIRETO (1+2), por ano*\n"
    f"ITERJ UG 133100 · MGS CNPJ 19.088.605/0001-04\n"
    f"_Fonte: SIAFE-Rio direto (sem TFE), deduplicado_\n\n"
    f"*{n} OBs* · Total pago: *R$ {brl(total)}*\n\n"
    f"*Por ano:*\n{linhas_resumo}\n\n"
    f"⚠ Anos com OBs de valor repetido (possível reemissão/estorno) sinalizados no anexo.\n"
    f"📎 Detalhe das {n} OBs (data, valor, competência, status, RE/PD) no arquivo."
)


def key(nm):
    m = re.search(rf"^{nm}=(.+)$", ENV.read_text(), re.M)
    return m.group(1).strip().strip('"').strip("'") if m else ""


token, chat = key("TELEGRAM_BOT_TOKEN"), key("TELEGRAM_CHAT_ID")
base = f"https://api.telegram.org/bot{token}"
r1 = httpx.post(f"{base}/sendMessage", data={"chat_id": chat, "text": msg, "parse_mode": "Markdown"}, timeout=30)
print("sendMessage:", r1.status_code, r1.json().get("ok"))
with open(OUT, "rb") as f:
    r2 = httpx.post(f"{base}/sendDocument",
                    data={"chat_id": chat, "caption": f"ITERJ→MGS (SIAFE direto) — {n} OBs · R$ {brl(total)}"},
                    files={"document": ("iterj_mgs_obs_siafe_por_ano.txt", f, "text/plain")}, timeout=60)
print("sendDocument:", r2.status_code, r2.json().get("ok"))
print("doc:", OUT, "| total:", n, "OBs R$", brl(total))
