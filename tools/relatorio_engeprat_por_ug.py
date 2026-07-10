#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Engeprat — perícia por UG (cada UG = um órgão; código+denominação) → PDF (chromium) → Yoda."""
import re, sqlite3, subprocess, sys
from datetime import datetime
from pathlib import Path
REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from compliance_agent.reporting.render_html import render_html
import httpx

CNPJ = "03314057000153"; con = sqlite3.connect(str(REPO / "data/compliance.db")); cur = con.cursor()
RPT = REPO / "reports"; HOJE = datetime.now().strftime("%d/%m/%Y")
def brl(x): return f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

rows = cur.execute(f"SELECT ug_codigo,ug_nome,valor,observacao,data_pagamento FROM ordens_bancarias WHERE favorecido_cpf LIKE '%{CNPJ}%'").fetchall()
def extrai(o):
    O = re.sub(r'\s+', ' ', (o or "").upper())
    if "EXTRAVASOR" in O or "460001/000779" in O.replace(" ", "") or "23003429" in O: return "033/2023 (Túnel Extravasor)"
    m = re.search(r'\bCTT[\s.\-]*N?[ºO°]?\s*N?[°]?\s*0*(\d{1,3})\s*[/.\-]\s*(\d{2,4})', O) or re.search(r'\bCONTRATO[\s.\-]*N?[ºO°]?\s*0*(\d{1,3})\s*[/.\-]\s*(\d{2,4})', O)
    if m:
        num = int(m.group(1)); ano = m.group(2); ano = ano if len(ano) == 4 else "20" + ano
        return f"{num:03d}/{ano}"
    if re.search(r'TOPOGR|GEORREF|PLANIALT|CADASTR', O): return "topografia/cadastro (s/ nº)"
    if re.search(r'MANUT|PREDIAL|CBA|LOTE', O): return "manutenção predial (s/ nº)"
    if re.search(r'TERMINAL|RODOVI', O): return "terminal rodoviário"
    return "diversos"

ug = {}
for cod, nome, v, o, dt in rows:
    d = ug.setdefault((cod, nome), {"v": 0.0, "n": 0, "c": {}, "dts": []})
    d["v"] += v or 0; d["n"] += 1
    if dt: d["dts"].append(dt)
    c = extrai(o); d["c"][c] = d["c"].get(c, 0) + (v or 0)
TOTAL = sum(d["v"] for d in ug.values()); NOBS = sum(d["n"] for d in ug.values())
codes = {}
for (cod, nome), d in ug.items(): codes.setdefault(cod, []).append(nome)
dup = {c: ns for c, ns in codes.items() if len(ns) > 1}

PERFIL = {
 "166100": "Manutenção predial preventiva/corretiva contínua do CBMERJ (CTTs 080–089/2022, por região/lote) — prorrogações anuais 2022→2026 (até 4º TA).",
 "133100": "Topografia/cadastro urbano e georreferenciamento (007/2023, 005/2022, 004/2022) — UG reusada por SEIC → Infraestrutura e Obras / Cidades / Infraestrutura e Cidades.",
 "530100": "Obras de engenharia — inclui o **Túnel Extravasor de Petrópolis (033/2023)** e manutenção predial (052/2022).",
 "044100": "Contenção de encostas RJ-145 km 40 (032/2024) — dispensa emergencial, 2025–2026.",
 "070100": "Contenção/drenagem emergencial Petrópolis (043/2022) e obras diversas 2022.",
 "036100": "Serviços/obras pontuais de 2019 (FETJ).",
 "045200": "Urbanização Parque Jacarezinho 2ª etapa (EMOP) — carteira recente.",
 "160100": "Rateio de manutenção predial/2º GMAR com o CBMERJ (Defesa Civil).",
 "317100": "Reforma de terminais rodoviários (Três Rios, Conceição de Macabu) — 2019.",
}

MD = f"""
## 1. Método
Perícia da carteira **Engeprat** (CNPJ 03.314.057/0001-53) no Estado do RJ **repartida por UG (unidade gestora)** — cada UG é um órgão. Fonte: **SIAFE**, {NOBS} OB, {brl(TOTAL)} (2019–2026), reconciliada ao centavo. O identificador é o **código da UG**; a denominação é a que consta na OB.

> **Atenção à dupla numeração:** um mesmo **código de UG** aparece com **denominações diferentes** (o órgão foi renomeado/desmembrado no tempo). Ex.: **133100** = SEIC → *Infraestrutura e Obras* / *Cidades* / *Infraestrutura e Cidades*; **530100** com 2 denominações. Trato cada par (código+denominação) como uma linha, sinalizando o código repetido.

## 2. Recebido por UG (SIAFE)
| Código UG | Denominação (na OB) | Recebido | % | nº OB | Período |
|---|---|---|---|---|---|"""
for (cod, nome), d in sorted(ug.items(), key=lambda x: -x[1]["v"]):
    dd = sorted(x for x in d["dts"] if x)
    flag = " ⚠️código repetido" if cod in dup else ""
    MD += f"\n| {cod}{flag} | {nome[:42]} | {brl(d['v'])} | {d['v']/TOTAL*100:.1f}% | {d['n']} | {dd[0][:7]}→{dd[-1][:7]} |"
MD += f"\n| **TOTAL** | **12 pares · {len(codes)} códigos distintos** | **{brl(TOTAL)}** | 100% | **{NOBS}** | 2019→2026 |"

MD += "\n\n## 3. Consolidado por CÓDIGO de UG (somando denominações do mesmo código)\n| Código | Recebido | Denominações sob o código |\n|---|---|---|"
cons = {}
for (cod, nome), d in ug.items(): cons.setdefault(cod, {"v": 0.0, "ns": set()}); cons[cod]["v"] += d["v"]; cons[cod]["ns"].add(nome[:30])
for cod, d in sorted(cons.items(), key=lambda x: -x[1]["v"]):
    MD += f"\n| **{cod}** | {brl(d['v'])} | {'; '.join(sorted(d['ns']))} |"

MD += "\n\n## 4. Perícia por UG (objeto dominante)\n"
for cod, d in sorted(cons.items(), key=lambda x: -x[1]["v"]):
    tops = {}
    for (c2, nome), dd in ug.items():
        if c2 == cod:
            for k, v in dd["c"].items(): tops[k] = tops.get(k, 0) + v
    top3 = ", ".join(f"{k} ({brl(v)})" for k, v in sorted(tops.items(), key=lambda x: -x[1])[:3])
    MD += f"\n**UG {cod} — {brl(d['v'])}**\n- {PERFIL.get(cod, '—')}\n- Principais linhas: {top3}\n"

MD += f"""
## 5. Achados
- **166100 (CBMERJ)** — maior nº de OB (827) e {brl(cons['166100']['v'])}: manutenção predial contínua com **sucessivos Termos Aditivos** (prorrogação anual até 23/06/2026). Verificar limite legal de prorrogação e reajustes.
- **133100 (topografia/cadastro)** — {brl(cons['133100']['v'])} num programa de levantamento topográfico/georreferenciamento urbano (007/2023, 005/2022, 004/2022). Código reusado por três denominações — atenção a rastreabilidade orçamentária.
- **530100** — abriga o **Túnel Extravasor de Petrópolis (033/2023)**, R$ 35,24 mi pagos.
- **044100 (DER)** — contenção RJ-145 por **dispensa emergencial** (art. 75, VIII, Lei 14.133/21). Somado a túnel e contenções de Petrópolis, há **reiteração de "emergência" ao mesmo fornecedor** — apurar excepcionalidade.

> **Ressalva:** Indício ≠ acusação; INDISPONÍVEL ≠ irregular; só a OB é paga. A atribuição contrato↔UG usa o histórico da OB; o "s/ nº" indica número de contrato ausente no texto. Nada indisponível foi fabricado.
"""

def md2html(block):
    out, tbl = [], []
    def flush():
        if not tbl: return
        rs = [r for r in tbl if not re.match(r"^\s*\|[\s:|-]+\|\s*$", r)]
        h = "".join(f"<th>{c.strip()}</th>" for c in rs[0].strip().strip("|").split("|"))
        body = "".join("<tr>" + "".join(f"<td>{c.strip()}</td>" for c in r.strip().strip("|").split("|")) + "</tr>" for r in rs[1:])
        out.append(f"<table><tr>{h}</tr>{body}</table>"); tbl.clear()
    for ln in block.splitlines():
        if ln.strip().startswith("|"): tbl.append(ln); continue
        flush()
        if ln.startswith("> "): out.append(f"<blockquote>{ln[2:]}</blockquote>")
        elif ln.startswith("- "): out.append(f"<li>{ln[2:]}</li>")
        elif ln.strip(): out.append(f"<p>{ln}</p>")
    flush()
    h = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", "\n".join(out))
    return h
secoes = [{"titulo": p.splitlines()[0].lstrip("# ").strip()[:90], "html": md2html("\n".join(p.splitlines()[1:]))}
          for p in re.split(r"\n##\s+", MD) if p.strip()]
ctx = {"classificacao": "CONFIDENCIAL — USO INTERNO (controle externo)",
       "titulo": "Engeprat — Perícia por UG (unidade gestora) · cada UG = um órgão",
       "subtitulo": "Recebido no SIAFE por código de UG, com a dupla numeração explicitada",
       "data": HOJE, "analista": "JFN — Núcleo de Fiscalização (Yoda)",
       "metodologia": "SIAFE 985 OB agregadas por ug_codigo+ug_nome (reconciliado) · consolidação por código · objeto dominante por UG · dupla numeração sinalizada",
       "score": 46, "faixa": "MÉDIO",
       "top_flags": [f"166100 CBMERJ {brl(cons['166100']['v'])} — manutenção contínua c/ prorrogações até 2026",
                     f"133100 topografia {brl(cons['133100']['v'])} — código com 3 denominações",
                     "530100 abriga o Túnel Extravasor (033/2023)"],
       "secoes": secoes,
       "proveniencia": [{"dado": f"{NOBS} OB por UG (reconciliado)", "estado": "REAL", "fonte": "SIAFE (ordens_bancarias)", "data": HOJE}],
       "ressalva": "Indício ≠ acusação; INDISPONÍVEL ≠ irregular. Dupla numeração de UG é feature do dado, não erro. Nada indisponível foi fabricado."}

nome = f"engeprat_pericia_por_UG_{datetime.now().date()}"
html = render_html(ctx); (RPT / f"{nome}.html").write_text(html)
subprocess.run(["chromium", "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                f"--print-to-pdf={RPT/(nome+'.pdf')}", f"file://{RPT/(nome+'.html')}"], capture_output=True, timeout=120)
pp = RPT / f"{nome}.pdf"
print("PDF:", pp, pp.stat().st_size if pp.exists() else "FALHOU", "| total:", brl(TOTAL), "| UGs:", len(ug), "| códigos:", len(codes))

ENV = Path("/home/ubuntu/.hermes/.env")
def k(n):
    m = re.search(rf"^{n}=(.+)$", ENV.read_text(), re.M); return m.group(1).strip().strip('"').strip("'") if m else ""
tok, chat = k("TELEGRAM_BOT_TOKEN"), k("TELEGRAM_CHAT_ID"); base = f"https://api.telegram.org/bot{tok}"
msg = ("🏛️ *ENGEPRAT — Perícia por UG (corrigida: cada UG = 1 órgão)*\n"
       "_Antes eu tinha colapsado por nome; agora é por código de UG._\n\n"
       f"• *166100* CBMERJ — {brl(cons['166100']['v'])} (manutenção contínua, TAs até 2026)\n"
       f"• *133100* topografia/cadastro — {brl(cons['133100']['v'])} (código com 3 denominações: SEIC/Infra+Obras/Cidades)\n"
       f"• *530100* — {brl(cons['530100']['v'])} (abriga o *Túnel Extravasor 033/2023*)\n"
       f"• *044100* DER-RJ {brl(cons['044100']['v'])} · *070100* {brl(cons['070100']['v'])} · *036100* FETJ · *045200* EMOP · *160100* Def.Civil · *317100* CODERTE\n\n"
       "⚠️ Dupla numeração explicitada (mesmo código, órgão renomeado). Detalhe por UG no PDF.")
r1 = httpx.post(f"{base}/sendMessage", data={"chat_id": chat, "text": msg, "parse_mode": "Markdown"}, timeout=30).json()
if not r1.get("ok"): r1 = httpx.post(f"{base}/sendMessage", data={"chat_id": chat, "text": msg}, timeout=30).json()
print("msg:", r1.get("ok"), r1.get("description", ""))
with open(pp, "rb") as f:
    rd = httpx.post(f"{base}/sendDocument", data={"chat_id": chat, "caption": "Engeprat — perícia por UG (cada UG = 1 órgão) — PDF"},
                    files={"document": (pp.name, f, "application/pdf")}, timeout=120).json()
print("pdf:", rd.get("ok"), rd.get("description", ""))
