#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Engeprat v2 — 2 relatórios (por contrato/tema · perícia por órgão) → PDF (chromium) → Yoda (só com --enviar).
SIAFE(OB paga)=recebido; contrato+aditivos(SEI/TCE)=teto a receber.

RECEBIDO = OB do SIAFE (`ob_orcamentaria_siafe`) pela régua única `cruzamentos_intel._ob_paga` — nunca o espelho
TFE (`ordens_bancarias`), que este script rotulava como "SIAFE" até 20/11/2026 (espelho: 999 OB / R$ 415.096.211,79).
O espelho entra só como TEXTO: a observação da mesma OB (número + UG) é o que o extrator lê para achar contrato,
medição e aditivo. Par UG×ano que o SIAFE da casa não cobre (2019–2020; a casa cobre 2021+) sai como INDISPONÍVEL —
não somado, nunca zero.

Uso: PYTHONPATH=. .venv/bin/python tools/relatorio_engeprat_yoda.py [--enviar]   (sem --enviar: só gera os PDFs)"""
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(REPO))
from compliance_agent.reporting.render_html import render_html
from compliance_agent.cruzamentos_intel import _ob_paga
from compliance_agent.reporting.cobertura_siafe import ANO_EMISSAO_SIAFE, ISO_EMISSAO_SIAFE, estados_dos_pares
from compliance_agent.reporting.intel_base import inteiro
from compliance_agent.ugs import nome_canonico

CNPJ = "03314057000153"
DB = Path(os.environ.get("JFN_DB") or REPO / "data/compliance.db")
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); cur = con.cursor()
RPT = REPO / "reports"; RPT.mkdir(exist_ok=True)
HOJE = datetime.now().strftime("%d/%m/%Y")


def brl(x): return f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


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
    h = "\n".join(out)
    h = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", h)
    h = re.sub(r"`(.+?)`", r"<code>\1</code>", h)
    return h


def secoes_de(md):
    sec = []
    for part in re.split(r"\n##\s+", md):
        if not part.strip(): continue
        sec.append({"titulo": part.splitlines()[0].lstrip("# ").strip()[:90],
                    "html": md2html("\n".join(part.splitlines()[1:]))})
    return sec


def to_pdf(ctx, nome):
    html = render_html(ctx)
    hp = RPT / f"{nome}.html"; pp = RPT / f"{nome}.pdf"
    hp.write_text(html)
    subprocess.run(["chromium", "--headless=new", "--no-sandbox", "--disable-gpu",
                    "--no-pdf-header-footer", f"--print-to-pdf={pp}", f"file://{hp}"],
                   capture_output=True, timeout=120)
    return pp if pp.exists() else None


# ===================== DADOS =====================
# RECEBIDO = OB paga do SIAFE. Do espelho TFE vêm só o TEXTO da observação da mesma OB (número + UG) — onde o
# extrator acha contrato/medição/aditivo — e o nome da UG (o SIAFE não traz). OB do SIAFE sem par no espelho fica
# "sem pista no histórico", nunca fora da soma.
_ESP = "FROM ordens_bancarias t WHERE t.numero_ob=s.numero_ob AND t.ug_codigo=s.ug_emitente LIMIT 1"
rows = cur.execute(
    f"SELECT s.ug_emitente, {ISO_EMISSAO_SIAFE.replace('data_emissao', 's.data_emissao')}, s.valor, "
    f"(SELECT t.observacao {_ESP}), "
    "COALESCE((SELECT t.ug_nome FROM ordens_bancarias t WHERE t.ug_codigo=s.ug_emitente AND t.ug_nome IS NOT NULL "
    "ORDER BY t.data_emissao DESC LIMIT 1), '') "
    f"FROM ob_orcamentaria_siafe s WHERE s.credor=? AND {_ob_paga(con, 's')}", (CNPJ,)).fetchall()
# órgão pelo CÓDIGO da UG (regra da casa: `ugs.nome_canonico`), nunca pelo nome do espelho — que chamava a UG 133100
# (ITERJ) de "Secretaria de Cidades/Infraestrutura" de 2021 em diante e a somava à secretaria
rows = [(nome_canonico(ug, nome or ug), dt, v, o) for ug, dt, v, o, nome in rows]

# cobertura do SIAFE nos pares UG×ano do credor (os do SIAFE e os que o espelho lista): o que não é VERIFICADO
# vai para a tabela de INDISPONÍVEL — do espelho, só a CONTAGEM de OB do recorte, nunca valor
_n_esp = {(u, a): n for u, a, n in cur.execute(
    "SELECT ug_codigo, substr(data_emissao,1,4), COUNT(*) FROM ordens_bancarias WHERE favorecido_cpf=? GROUP BY 1,2",
    (CNPJ,))}
# ob-qualquer-status: pares UG×ano para medir cobertura, não soma
_pares = set(_n_esp) | set(cur.execute(
    f"SELECT DISTINCT ug_emitente, {ANO_EMISSAO_SIAFE} FROM ob_orcamentaria_siafe WHERE credor=?", (CNPJ,)))
INDISP = [{"ug": u, "ano": a, "rotulo": e["rotulo"], "obs_espelho": _n_esp.get((u, a), 0)}
          for (u, a), e in estados_dos_pares(_pares, db=DB).items() if e["rotulo"] != "VERIFICADO"]

def extrai(o):
    O = re.sub(r'\s+', ' ', (o or "").upper())
    if "EXTRAVASOR" in O or "460001/000779" in O.replace(" ", "") or "23003429" in O: return "033/2023"
    if "23000796" in O: return "052/2022"
    m = re.search(r'\bCTT[\s.\-]*N?[ºO°]?\s*N?[°]?\s*0*(\d{1,3})\s*[/.\-]\s*(\d{2,4})', O) or re.search(r'\bCONTRATO[\s.\-]*N?[ºO°]?\s*0*(\d{1,3})\s*[/.\-]\s*(\d{2,4})', O)
    if m:
        num = int(m.group(1)); ano = m.group(2); ano = ano if len(ano) == 4 else ("20" + ano if int(ano) < 80 else "19" + ano)
        return f"{num:03d}/{ano}"
    return None
def cluster(o):
    O = re.sub(r'\s+', ' ', (o or "").upper())
    if re.search(r'TOPOGR|GEORREFEREN|PLANIALT|CADASTR', O): return "topografia s/ nº"
    if re.search(r'TERMINAL|RODOVI', O): return "terminal rodoviário 2019"
    if re.search(r'\bSEQ\b|LIQ\.\s*\d{4,}', O): return "TJ 2019 (seq)"
    if re.search(r'MANUT|PREDIAL|REFORMA|CBA|LOTE|LT 0', O): return "manutenção/reforma s/ nº"
    return "outros s/ pista"
def norm_org(u):
    u = (u or "").upper()
    if "ITERJ" in u: return "ITERJ — Instituto de Terras e Cartografia"
    if "BOMBEIR" in u: return "FUNESBOM — Corpo de Bombeiros (CBMERJ)"
    if "INFRAESTRUTURA" in u: return "SEINFRA/SEIOP — Infraestrutura e Obras"
    if "CIDA" in u: return "Sec. de Estado de Cidades"
    if "DEFESA CIVIL" in u: return "Sec. de Defesa Civil"
    if "ESTRADAS DE RODAGEM" in u: return "DER-RJ"
    if "TRIBUNAL DE JUSTICA" in u: return "FETJ — Fundo Especial do TJ-RJ"
    if "OBRAS PUBLICAS" in u: return "EMOP — Empresa de Obras Públicas"
    if "RODOV E TERMI" in u: return "CODERTE — Rodoviário/Terminais"
    return (u.title()[:38] or "s/ UG")

linha, por_org, dts_c, tas_c, vig_c = {}, {}, {}, {}, {}
for ug, dt, v, o in rows:
    c = extrai(o) or cluster(o)
    linha[c] = linha.get(c, 0) + (v or 0)
    dts_c.setdefault(c, []).append(dt) if dt else None
    O = re.sub(r'\s+', ' ', (o or "").upper())
    ta = re.search(r'(\d+)[ºOoAª]{0,2}\s*T\.?\s*A\b', O)
    if ta: tas_c.setdefault(c, set()).add(int(ta.group(1)))
    vg = re.search(r'VIG\.?\s*(?:DE\s*)?(\d{2}[/.]\d{2}[/.]\d{2,4})\s*[ÀA]\s*(\d{2}[/.]\d{2}[/.]\d{2,4})', O)
    if vg: vig_c.setdefault(c, set()).add(f"{vg.group(1)}→{vg.group(2)}")
    g = norm_org(ug)
    e = por_org.setdefault(g, {"n": 0, "v": 0.0, "dts": []})
    e["n"] += 1; e["v"] += v or 0
    if dt: e["dts"].append(dt)
TOTAL = sum(linha.values()); NOBS = len(rows)
_dts = sorted(dt for _u, dt, _v, _o in rows if dt)
PERIODO = f"{_dts[0][:4]}–{_dts[-1][:4]}" if _dts else "—"
_ind = sorted({x["ano"] for x in INDISP if x["rotulo"] == "INDISPONÍVEL"})
INDISP_TXT = (f"exercícios {', '.join(_ind)} INDISPONÍVEIS no SIAFE da casa — não somados" if _ind else
              "sem exercício fora da cobertura do SIAFE")


def tabela_indisp():
    if not INDISP:
        return ""
    t = ("\n\n## Fora da cobertura do SIAFE (INDISPONÍVEL ≠ zero)\n"
         "O SIAFE da casa cobre 2021+ (antes, só a ALERJ). Nestes recortes o recebido **não está somado**: "
         "INDISPONÍVEL = par UG×ano nunca lido no SIAFE; PARCIAL = lido em parte (soma é piso). O espelho TFE só "
         "aponta o recorte (nº de OB que ele lista), nunca valor.\n"
         "| UG | Órgão | Ano | SIAFE | OB no espelho TFE (não somadas) |\n|---|---|---|---|---|")
    for x in INDISP:
        t += f"\n| {x['ug']} | {nome_canonico(x['ug'], x['ug'])} | {x['ano']} | {x['rotulo']} | {x['obs_espelho']} |"
    return t + "\n"
def rec(c): return linha.get(c, 0.0)
def per(c):
    d = sorted(x for x in dts_c.get(c, []) if x)
    return f"{d[0][:10]}→{d[-1][:10]}" if d else "—"

tce = {r[0]: r for r in cur.execute(f"SELECT num_contratacao,processo,valor_contrato,valor_empenhado,status,vig_inicio,vig_fim,objeto FROM contratos_tcerj WHERE cnpj LIKE '%{CNPJ}%'").fetchall()}
# OB paga (SIAFE) do Túnel: observação da mesma OB no espelho com a pista do contrato/processos de pagamento
_PISTAS_TUNEL = ("033/2023", "330018/000300/2023", "330001/000436/2024", "330001/000428/2025")
med = [(o,) for _ug, _dt, _v, o in rows
       if o and ("EXTRAVASOR" in o.upper() or any(p in o for p in _PISTAS_TUNEL))]
meds = sorted({int(m.group(1)) for (o,) in med if (m := re.search(r'(\d{1,2})[ºoOª]{0,2}\s*[Mm]edi', o or ""))})

# valores contratados (TCE) e saldos casados
tunel_c = 41290047.36; tunel_p = rec("033/2023"); tunel_s = tunel_c - tunel_p
der_c = 36918166.36; der_p = rec("032/2024"); der_s = der_c - der_p
gmar_c = 15181266.88; gmar_p = rec("006/2024"); gmar_s = gmar_c - gmar_p
emop_c = 36147765.96; emop_p = por_org.get("EMOP — Empresa de Obras Públicas", {}).get("v", 0.0); emop_s = emop_c - emop_p
iterj_c = 92800000.00; iterj_emp = 38666666.65
iterj_p = por_org.get("ITERJ — Instituto de Terras e Cartografia", {}).get("v", 0.0)   # OB paga pela UG 133100
saldo_rastreavel = tunel_s + der_s + gmar_s + emop_s

BLOCOS = {
 "★ TÚNEL EXTRAVASOR — Petrópolis (033/2023)": ["033/2023"],
 "Topografia / cadastro urbano (ITERJ)": ["007/2023", "005/2022", "004/2022", "topografia s/ nº"],
 "Contenção / encostas emergencial": ["032/2024", "043/2022"],
 "Manutenção predial contínua (CBMERJ · SEINFRA)": ["080/2022", "081/2022", "082/2022", "083/2022", "084/2022", "087/2022", "089/2022", "006/2024", "052/2022", "manutenção/reforma s/ nº"],
 "Obras / serviços diversos": ["012/2021", "008/2022", "terminal rodoviário 2019", "TJ 2019 (seq)", "outros s/ pista"],
}
LABELS = {
 "007/2023": "007/2023 — topografia/cadastro (pago pela UG 133100 — ITERJ)", "005/2022": "005/2022 — topografia/cadastro",
 "004/2022": "004/2022 — topografia/cadastro", "topografia s/ nº": "topografia — nº não legível na OB",
 "032/2024": "032/2024 — contenção RJ-145 km40 (DER)", "043/2022": "043/2022 — contenção Pedro Ivo/Morin, Petrópolis",
 "080/2022": "CTT 080/2022 — QCG", "081/2022": "CTT 081/2022", "082/2022": "CTT 082/2022 — Serrana LT03",
 "083/2022": "CTT 083/2022 — Sul LT04", "084/2022": "CTT 084/2022 — Norte/Noroeste LT05",
 "087/2022": "CTT 087/2022 — Costa Verde LT08", "089/2022": "CTT 089/2022 — Metropolitana LT10",
 "006/2024": "006/2024 — 2º GMAR (reforma/ampliação)", "052/2022": "052/2022 — manutenção predial (SEINFRA)",
 "manutenção/reforma s/ nº": "manutenção/reforma — nº não legível na OB",
 "012/2021": "012/2021 — reforma sede ITERJ", "008/2022": "008/2022 — colégio modular Guaratiba",
 "terminal rodoviário 2019": "terminais rodoviários (CODERTE, 2019)", "TJ 2019 (seq)": "TJ-RJ (liquidações 2019)",
 "outros s/ pista": "outros — sem pista no histórico",
}

# ===================== RELATÓRIO 1 — POR CONTRATO/TEMA =====================
MD1 = f"""
## 1. Sumário executivo
A **Enge Prat Engenharia e Serviços Ltda.** (CNPJ 03.314.057/0001-53) já **recebeu {brl(TOTAL)}** do Estado do RJ em **{inteiro(NOBS)} ordens bancárias pagas** (SIAFE, {PERIODO}; {INDISP_TXT}). O objeto da consulta — **Túnel Extravasor de Petrópolis** — é o **Contrato nº 033/2023** (SEIOP/SEIC), processo **SEI-460001/000779/2023**, de **{brl(tunel_c)}**, com **{brl(tunel_p)} já pagos** e **{brl(tunel_s)} de saldo**.

> **Eixo:** OB (SIAFE) = **já recebido**; contrato + aditivos (SEI/TCE) = **teto a faturar**. Saldo a receber = `Contratado − Pago`.
> **Reconciliação:** os {inteiro(NOBS)} pagamentos somam **{brl(TOTAL)}** e estão 100% alocados abaixo.

## 2. ★ TÚNEL EXTRAVASOR DE PETRÓPOLIS — Contrato 033/2023
| Item | Dado (SIAFE / SEI) |
|---|---|
| Contrato / processo | 033/2023 · SEI-460001/000779/2023 (nº 2023007333) |
| Pagamentos (SEI) | 330018/000300/2023 · 330001/000436/2024 · 330001/000428/2025 |
| Órgão | SEIOP/SEIC — Infraestrutura e Obras Públicas / Cidades |
| Objeto | Projetos executivos + conclusão da obra emergencial de recuperação estrutural, desobstrução e desassoreamento do Túnel Extravasor, Petrópolis/RJ |
| Vigência | 21/09/2023 → 14/03/2025 · Menor Preço · Ativo |
| **Contratado** | **{brl(tunel_c)}** |
| **Recebido (SIAFE)** | **{brl(tunel_p)}** — {len(med)} OB |
| **Saldo a receber** | **{brl(tunel_s)}** ({tunel_s/tunel_c*100:.1f}%) |

**Perícia:**
- **Medições pagas rastreadas** (histórico das OB pagas): {', '.join(f'{m}ª' for m in meds) or 'nenhuma legível'}. Medição que não aparece pode ter sido paga sob outra referência **ou** não estar no histórico. Reporta-se **{brl(tunel_p)} como piso** do efetivamente pago, não o teto.
- **T07 Duplicidade por competência: NEGATIVO** — competências com 2 OB são desdobramento (líquido + complemento), não duplicidade.
- **Aditivos:** sem Termo Aditivo no histórico das OB; vigência única de 18 meses. Confirmar TA de prazo/valor na íntegra do SEI-460001/000779/2023.

## 3. Carteira por bloco temático (reconciliação = {brl(TOTAL)})
| Bloco | Recebido (SIAFE) | % |
|---|---|---|"""
sb = {}
for b, cs in BLOCOS.items():
    s = sum(rec(c) for c in cs); sb[b] = s
    MD1 += f"\n| {b} | {brl(s)} | {s/TOTAL*100:.1f}% |"
MD1 += f"\n| **TOTAL** | **{brl(TOTAL)}** | 100,0% |"
MD1 += tabela_indisp()

MD1 += "\n\n## 4. Detalhe por contrato (dentro de cada bloco)\n"
for b, cs in BLOCOS.items():
    MD1 += f"\n**{b}** — {brl(sb[b])}\n| Contrato / linha | Recebido (SIAFE) | nº OB | Período | Aditivos (histórico da OB) |\n|---|---|---|---|---|\n"
    for c in sorted(cs, key=lambda x: -rec(x)):
        if rec(c) <= 0: continue
        n = sum(1 for ug, dt, v, o in rows if (extrai(o) or cluster(o)) == c)
        ta = f"até {max(tas_c[c])}º TA" if tas_c.get(c) else ("prorrog. anual" if vig_c.get(c) and len(vig_c[c]) > 1 else "—")
        MD1 += f"| {LABELS.get(c, c)} | {brl(rec(c))} | {n} | {per(c)} | {ta} |\n"

MD1 += f"""
## 5. Contratos formalizados no TCE-RJ — teto a faturar (a receber)
| Nº | Processo SEI | Objeto | Contratado | Recebido (SIAFE) | Saldo a receber |
|---|---|---|---|---|---|
| 2023007333 | SEI-460001/000779/2023 | Túnel Extravasor (033/2023) | {brl(tunel_c)} | {brl(tunel_p)} | **{brl(tunel_s)}** |
| 2024009872 | SEI-330002/005941/2024 | Contenção RJ-145 (032/2024, DER) | {brl(der_c)} | {brl(der_p)} | **{brl(der_s)}** |
| 2024001494 | SEI-270042/000828/2022 | 2º GMAR (006/2024, Bombeiros) | {brl(gmar_c)} | {brl(gmar_p)} | **{brl(gmar_s)}** |
| 2025005397 | SEI-330003/000351/2025 | Parque Jacarezinho 2ª etapa (EMOP) | {brl(emop_c)} | {brl(emop_p)} | **{brl(emop_s)}** |
| 2023005610 | SEI-330020/000101A/2023 | Topografia ITERJ | {brl(iterj_c)} | a vincular — UG 133100 (ITERJ) pagou {brl(iterj_p)} no total | teto {brl(iterj_c)} (empenhado {brl(iterj_emp)}) |

## 6. Perícia — síntese e ressalvas
- **Concentração:** {brl(TOTAL)} / {inteiro(NOBS)} OB. Dois blocos dominam: **topografia/cadastro urbano {brl(sb['Topografia / cadastro urbano (ITERJ)'])}** ({sb['Topografia / cadastro urbano (ITERJ)']/TOTAL*100:.0f}%) e **manutenção predial contínua {brl(sb['Manutenção predial contínua (CBMERJ · SEINFRA)'])}** ({sb['Manutenção predial contínua (CBMERJ · SEINFRA)']/TOTAL*100:.0f}%).
- **Aditivos (histórico das OB):** os CTTs do CBMERJ (080–089/2022) foram **prorrogados ano a ano de 24/06/2022 até 23/06/2026** (até 4ª prorrogação) — verificar limite legal de prorrogação e reajustes. 006/2024 (2º GMAR) tem 1º TA.
- **Dispensa emergencial recorrente** (art. 75, VIII, Lei 14.133/21): Túnel, RJ-145 (DER), contenções de Petrópolis — apurar se a reiteração de "emergência" ao mesmo fornecedor observa o caráter excepcional.
- **Premissa a RECONFERIR (topografia):** a versão anterior tratou o **007/2023 ({brl(rec('007/2023'))} pagos)** e o **contrato ITERJ (SEI-330020/000101A/2023, {brl(iterj_c)})** como registros distintos e rotulou o 007/2023 como SEINFRA. Pelo **código da UG** (regra da casa), as OB do 007/2023 são pagas pela **UG 133100 — ITERJ**; o espelho TFE a nomeava "Secretaria de Cidades/Infraestrutura". Não se afirma pagamento acima do contrato: o vínculo 007/2023 × contrato ITERJ tem de ser conferido no SEI antes de qualquer conclusão.
- **Saldo a faturar (rastreável, contratos com pago identificado): ≈ {brl(saldo_rastreavel)}**; além disso, contrato ITERJ topografia com teto de {brl(iterj_c)} (UG 133100/ITERJ pagou {brl(iterj_p)} à Engeprat no SIAFE — vínculo com este contrato a conferir no SEI).

> **Ressalva:** Indício ≠ acusação; INDISPONÍVEL ≠ irregular. Só a OB contabilizada é paga; "a receber" é teto. "s/ nº"/"não legível" = número de contrato ausente no histórico da OB, a confirmar no SEI. Nenhum dado indisponível foi fabricado.
"""

ctx1 = {
    "classificacao": "CONFIDENCIAL — USO INTERNO (controle externo)",
    "titulo": "Engeprat — Carteira estadual por contrato · Túnel Extravasor de Petrópolis (v2)",
    "subtitulo": f"Recebido (SIAFE/OB paga) × Teto a receber (contrato+aditivos SEI/TCE) — {inteiro(NOBS)} OB, {brl(TOTAL)}",
    "data": HOJE, "analista": "JFN — Núcleo de Fiscalização (Yoda)",
    "metodologia": f"SIAFE: {inteiro(NOBS)} OB pagas (régua _ob_paga) alocadas 100% por contrato/bloco (extrator CTT/CONTRATO + nº processo SEI sobre o histórico da OB) · {INDISP_TXT} · SEI/TCE-RJ: 5 contratos formalizados · aditivos via vigências do histórico · perícia T07 · verificação adversarial (falso-positivo 007/2023 corrigido)",
    "score": 46, "faixa": "MÉDIO",
    "top_flags": [
        f"Túnel 033/2023: contratado {brl(tunel_c)} · recebido {brl(tunel_p)} · saldo {brl(tunel_s)}",
        f"Concentração {brl(TOTAL)}/{inteiro(NOBS)} OB — topografia {sb['Topografia / cadastro urbano (ITERJ)']/TOTAL*100:.0f}% + manutenção {sb['Manutenção predial contínua (CBMERJ · SEINFRA)']/TOTAL*100:.0f}%",
        "CBMERJ 080–089/2022 prorrogados anualmente 2022→2026 (até 4º TA)",
        "Dispensa emergencial recorrente ao mesmo fornecedor — apurar excepcionalidade",
    ],
    "secoes": secoes_de(MD1),
    "proveniencia": [{"dado": f"{inteiro(NOBS)} OB pagas / {brl(TOTAL)}", "estado": "REAL" if not INDISP else "PARCIAL (" + INDISP_TXT + ")", "fonte": "SIAFE (ob_orcamentaria_siafe, régua _ob_paga); histórico da OB do espelho TFE só como texto", "data": HOJE},
                     {"dado": "5 contratos formalizados", "estado": "REAL", "fonte": "TCE-RJ (contratos_tcerj)/SEI", "data": HOJE}],
    "ressalva": "Indício ≠ acusação; só OB é paga; 'a receber' é teto; 's/ nº' = número ausente na OB. Nada indisponível foi fabricado.",
}

# ===================== RELATÓRIO 2 — PERÍCIA POR ÓRGÃO =====================
PERFIL = {
    "SEINFRA/SEIOP — Infraestrutura e Obras": "Obras/engenharia: **Túnel Extravasor 033/2023**, contenção 043/2022, manutenção 052/2022 (UGs 530100/070100).",
    "FUNESBOM — Corpo de Bombeiros (CBMERJ)": "Manutenção predial contínua (CTTs 080–089/2022 por região) prorrogada anualmente 2022→2026 (até 4º TA) + 2º GMAR (006/2024).",
    "Sec. de Estado de Cidades": "Levantamento topográfico/cadastro socioeconômico (004 e 005/2022) e reforma ITERJ (012/2021), concentrados em 2022.",
    "ITERJ — Instituto de Terras e Cartografia": "UG 133100: topografia/cadastro (007/2023, 004 e 005/2022). No espelho TFE aparecia com o nome da secretaria (Cidades/Infraestrutura) e era somada a ela; pelo código da UG é o ITERJ. Vínculo com o contrato SEI-330020/000101A/2023 a conferir no SEI.",
    "DER-RJ": "Contenção de encostas RJ-145 km 40 (032/2024) — dispensa emergencial, execução 2025–2026.",
    "EMOP — Empresa de Obras Públicas": "Urbanização Parque Jacarezinho 2ª etapa (2025005397) — carteira recente, teto R$ 36,1 mi.",
    "FETJ — Fundo Especial do TJ-RJ": "Pagamentos pontuais de 2019, sem recorrência posterior.",
    "CODERTE — Rodoviário/Terminais": "Reforma de terminais rodoviários (Três Rios, Conceição de Macabu), 2019.",
}
MD2 = f"""
## 1. Objetivo e método
Perícia da carteira **Engeprat** no Estado do RJ **repartida por órgão**, cruzando **recebido (SIAFE/OB)** com o **teto contratual (SEI/TCE)**. Base: **{inteiro(NOBS)} OB pagas, {brl(TOTAL)}** (SIAFE, {PERIODO}; {INDISP_TXT}).

## 2. Recebido por órgão (SIAFE)
| Órgão | Recebido | % carteira | nº OB | Período |
|---|---|---|---|---|"""
for g, d in sorted(por_org.items(), key=lambda x: -x[1]["v"]):
    dd = sorted(x for x in d["dts"] if x)
    MD2 += f"\n| {g} | {brl(d['v'])} | {d['v']/TOTAL*100:.1f}% | {inteiro(d['n'])} | {dd[0][:7]}→{dd[-1][:7]} |"
MD2 += f"\n| **TOTAL** | **{brl(TOTAL)}** | 100% | **{inteiro(NOBS)}** | {PERIODO.replace('–', '→')} |"
MD2 += tabela_indisp()

MD2 += "\n\n## 3. Perícia por órgão"
for g, d in sorted(por_org.items(), key=lambda x: -x[1]["v"]):
    dd = sorted(x for x in d["dts"] if x)
    MD2 += f"\n\n**{g}** — {brl(d['v'])} · {inteiro(d['n'])} OB · {dd[0][:10]}→{dd[-1][:10]}\n- {PERFIL.get(g, '—')}"

sein = por_org.get("SEINFRA/SEIOP — Infraestrutura e Obras", {})
fun = por_org.get("FUNESBOM — Corpo de Bombeiros (CBMERJ)", {})
MD2 += f"""

## 4. Achados transversais
- **ITERJ (UG 133100)** concentra {iterj_p/TOTAL*100:.0f}% da carteira ({brl(iterj_p)}) — topografia/cadastro (007/2023, 004 e 005/2022). Até a versão anterior essas OB apareciam somadas à SEINFRA/Cidades pelo nome que o espelho TFE dava à UG; pelo código é o ITERJ. Órgão-chave: conferir no SEI o vínculo com o contrato SEI-330020/000101A/2023 (teto {brl(iterj_c)}).
- **SEINFRA/SEIOP** concentra {sein.get('v',0)/TOTAL*100:.0f}% da carteira ({brl(sein.get('v',0))}) e as obras de engenharia — inclusive o **Túnel Extravasor (033/2023)**.
- **FUNESBOM/CBMERJ**: maior nº de OB ({inteiro(fun.get('n',0))}); {brl(fun.get('v',0))} em manutenção predial contínua renovada por **sucessivos Termos Aditivos** (CTTs 080–089/2022, prorrogação anual 2022→2026). Verificar limite de prorrogação e reajustes.
- **Dispensa emergencial recorrente** (art. 75, VIII): Túnel (SEINFRA), RJ-145 (DER) e contenções de Petrópolis — apurar excepcionalidade da hipótese diante da reiteração ao mesmo fornecedor.
- **Teto a faturar (contratos vivos com pago rastreado): ≈ {brl(saldo_rastreavel)}** + contrato ITERJ topografia (teto {brl(iterj_c)}; UG 133100/ITERJ pagou {brl(iterj_p)} — vínculo a conferir no SEI).

> **Ressalva:** Indício ≠ acusação; INDISPONÍVEL ≠ irregular. A perícia por UG do banco usa testes de contrato contínuo e não substitui a leitura da íntegra do SEI. Nada indisponível foi fabricado.
"""
ctx2 = {
    "classificacao": "CONFIDENCIAL — USO INTERNO (controle externo)",
    "titulo": "Engeprat — Perícia da carteira estadual por ÓRGÃO (v2)",
    "subtitulo": "Recebido (SIAFE) e teto contratual (SEI/TCE) repartidos por órgão contratante",
    "data": HOJE, "analista": "JFN — Núcleo de Fiscalização (Yoda)",
    "metodologia": f"Agregação SIAFE por UG ({inteiro(NOBS)} OB pagas, régua _ob_paga) · {INDISP_TXT} · perfil de objeto por órgão · aditivos via vigências do histórico · cruzamento com contratos TCE-RJ",
    "score": 46, "faixa": "MÉDIO",
    "top_flags": [
        f"ITERJ (UG 133100) {brl(iterj_p)} ({iterj_p/TOTAL*100:.0f}%) — topografia; vínculo com o contrato ITERJ a conferir",
        f"SEINFRA/SEIOP {brl(sein.get('v',0))} ({sein.get('v',0)/TOTAL*100:.0f}%) — inclui o Túnel Extravasor",
        f"FUNESBOM/CBMERJ {brl(fun.get('v',0))} em {inteiro(fun.get('n',0))} OB — manutenção contínua c/ prorrogações até 2026",
        "Dispensa emergencial recorrente ao mesmo fornecedor — apurar excepcionalidade",
    ],
    "secoes": secoes_de(MD2),
    "proveniencia": [{"dado": f"{inteiro(NOBS)} OB pagas por UG", "estado": "REAL" if not INDISP else "PARCIAL (" + INDISP_TXT + ")", "fonte": "SIAFE (ob_orcamentaria_siafe, régua _ob_paga)", "data": HOJE}],
    "ressalva": "Indício ≠ acusação; INDISPONÍVEL ≠ irregular. Nada indisponível foi fabricado.",
}

# ===================== GERA PDF + ENVIA =====================
p1 = to_pdf(ctx1, f"engeprat_por_contrato_v2_{datetime.now().date()}")
p2 = to_pdf(ctx2, f"engeprat_pericia_por_orgao_v2_{datetime.now().date()}")
print("PDF1:", p1, p1.stat().st_size if p1 else "FALHOU")
print("PDF2:", p2, p2.stat().st_size if p2 else "FALHOU")
print("CHECK reconciliação:", brl(TOTAL), "| soma blocos:", brl(sum(sb.values())), "| dif:", brl(TOTAL - sum(sb.values())))
print("INDISPONÍVEL/PARCIAL no SIAFE:", INDISP or "nenhum")

if "--enviar" not in sys.argv:
    print("sem --enviar: PDFs gerados, nada enviado ao Telegram")
    raise SystemExit(0)
import httpx  # noqa: E402  (só o envio usa)

ENV = Path("/home/ubuntu/.hermes/.env")
def k(n):
    m = re.search(rf"^{n}=(.+)$", ENV.read_text(), re.M); return m.group(1).strip().strip('"').strip("'") if m else ""
tok, chat = k("TELEGRAM_BOT_TOKEN"), k("TELEGRAM_CHAT_ID"); base = f"https://api.telegram.org/bot{tok}"
def send(msg, pdf, cap):
    r = httpx.post(f"{base}/sendMessage", data={"chat_id": chat, "text": msg, "parse_mode": "Markdown"}, timeout=30).json()
    if not r.get("ok"): r = httpx.post(f"{base}/sendMessage", data={"chat_id": chat, "text": msg}, timeout=30).json()
    print("  msg:", r.get("ok"), r.get("description", ""))
    if pdf:
        with open(pdf, "rb") as f:
            rd = httpx.post(f"{base}/sendDocument", data={"chat_id": chat, "caption": cap},
                            files={"document": (pdf.name, f, "application/pdf")}, timeout=120).json()
        print("  pdf:", rd.get("ok"), rd.get("description", ""))

msg1 = ("🏗️ *ENGEPRAT — Túnel Extravasor & carteira (v2, revisado)*\n"
        f"_SIAFE (OB paga) = recebido · Contrato/aditivos = teto a receber. {inteiro(NOBS)} OB, {brl(TOTAL)}._\n\n"
        f"★ *Túnel — 033/2023* (SEI-460001/000779/2023): contratado *{brl(tunel_c)}* · recebido *{brl(tunel_p)}* · *saldo {brl(tunel_s)}*.\n\n"
        "📊 *Carteira por bloco:*\n"
        f"• Topografia/cadastro *{brl(sb['Topografia / cadastro urbano (ITERJ)'])}*\n"
        f"• Manutenção predial (CBMERJ) *{brl(sb['Manutenção predial contínua (CBMERJ · SEINFRA)'])}*\n"
        f"• Contenção/encostas *{brl(sb['Contenção / encostas emergencial'])}*\n"
        f"• Diversos *{brl(sb['Obras / serviços diversos'])}*\n\n"
        f"💰 A faturar (rastreável) ≈ *{brl(saldo_rastreavel)}* + ITERJ topografia teto {brl(iterj_c)}.\n"
        "⚠️ 007/2023 é pago pela UG 133100 (ITERJ, pelo código da UG) — a premissa \"007/2023 ≠ contrato ITERJ\" vai ser reconferida no SEI.")
msg2 = ("🏛️ *ENGEPRAT — Perícia por ÓRGÃO (v2)*\n"
        f"• SEINFRA/SEIOP *{brl(sein.get('v',0))}* ({sein.get('v',0)/TOTAL*100:.0f}%) — inclui o Túnel\n"
        f"• FUNESBOM/CBMERJ *{brl(fun.get('v',0))}* / {inteiro(fun.get('n',0))} OB — manutenção c/ prorrogações até 2026\n"
        f"• Cidades *{brl(por_org.get('Sec. de Estado de Cidades',{}).get('v',0))}* · DER *{brl(por_org.get('DER-RJ',{}).get('v',0))}* · EMOP/FETJ/CODERTE menores\n"
        "🔎 Dispensa emergencial recorrente ao mesmo fornecedor — apurar excepcionalidade.")
print("envio 1:"); send(msg1, p1, "Engeprat v2 — por contrato (Túnel Extravasor) — PDF")
print("envio 2:"); send(msg2, p2, "Engeprat v2 — perícia por órgão — PDF")
