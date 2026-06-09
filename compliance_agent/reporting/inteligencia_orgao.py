# -*- coding: utf-8 -*-
"""
RELATÓRIO DE INTELIGÊNCIA DE ÓRGÃO — a contrapartida "por órgão" do relatório de fornecedor.

Em vez de "quanto um fornecedor recebeu", responde **"quanto um órgão (Unidade Gestora) pagou, e a
quem"**: total por ano, tabela de OBs individuais por ano, concentração POR FAVORECIDO (quais empresas
mais recebem) + HHI, e top fornecedores. Reaproveita os helpers do módulo de fornecedor (`inteligencia`).

Aceita o órgão por **nome (parcial)** ou **código de UG**. Ex.: "iterj", "bombeiros", "133100".
Se ambíguo, devolve {ambiguo:true, pergunta, candidatos} para o Yoda perguntar ao Mestre Jorge.

USO (CLI):
    cd ~/JFN && .venv/bin/python -m compliance_agent.reporting.inteligencia_orgao "iterj"
    cd ~/JFN && .venv/bin/python -m compliance_agent.reporting.inteligencia_orgao 133100 2025 2026

USO (API): POST /api/relatorio/orgao  {"orgao":"iterj"}  ou  {"ug":"133100"}  [, "anos":[2025,2026]]
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from collections import OrderedDict, defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

from compliance_agent import ugs
from compliance_agent.reporting.inteligencia import (
    cabecalho_frescor,
    _DB, _REPORTS, _hhi, _mc, _registrar_fonte, _render_parecer_pdf, _slug,
    _tab_header, _tab_row, fmt_cnpj, moeda, so_digitos,
)


# ───────────────────────────── resolução de órgão ─────────────────────────────

def buscar_orgaos(termo: str, limite: int = 8) -> list[dict]:
    """Resolve órgão por CÓDIGO de UG ou por NOME (parcial). Retorna [{ug, nome, total_pago, n_obs, n_forn}]."""
    termo = (termo or "").strip()
    if not termo or not _DB.exists():
        return []
    con = sqlite3.connect(_DB)
    con.row_factory = sqlite3.Row
    cands: "OrderedDict[str, dict]" = OrderedDict()
    try:
        # candidatos por nome canônico (mapa) — casa o termo no nome amigável (ex.: "iterj")
        alvo = termo.lower()
        ug_por_nome = {ug for ug, nome in ugs.carregar().items() if alvo in (nome or "").lower()}
        # candidatos por código direto
        cod = "".join(ch for ch in termo if ch.isdigit())
        ugs_match = set(ug_por_nome)
        if cod:
            ugs_match.add(cod)
        # candidatos por nome cru das OBs (ug_nome) — pega o ug_codigo correspondente
        for r in con.execute(
            "SELECT DISTINCT ug_codigo FROM ordens_bancarias WHERE lower(ug_nome) LIKE ? AND ug_codigo IS NOT NULL LIMIT 50",
            (f"%{alvo}%",)):
            if r["ug_codigo"]:
                ugs_match.add(str(r["ug_codigo"]).strip())
        # métricas de cada UG candidata
        for ug in ugs_match:
            r = con.execute(
                "SELECT COUNT(*) n, ROUND(SUM(valor),2) total, COUNT(DISTINCT favorecido_cpf) forn, "
                "MAX(ug_nome) ug_nome FROM ordens_bancarias WHERE ug_codigo=?", (ug,)).fetchone()
            if not r or not r["n"]:
                continue
            cands[ug] = {
                "ug": ug, "nome": ugs.nome_canonico(ug, "") or (r["ug_nome"] or f"UG {ug}"),
                "total_pago": float(r["total"] or 0.0), "n_obs": int(r["n"] or 0),
                "n_forn": int(r["forn"] or 0),
            }
    finally:
        con.close()
    return sorted(cands.values(), key=lambda c: (c["total_pago"], c["n_obs"]), reverse=True)[:limite]


# ───────────────────────────── consulta ─────────────────────────────

def consultar_orgao(ug: str, anos: Optional[list[int]] = None) -> dict:
    """OBs pagas PELA UG, por ano, com linhas individuais (favorecido) + concentração por favorecido."""
    out = {"tem_dados": False, "ug": ug, "anos": [], "total_geral": 0.0, "n_geral": 0,
           "por_ano": OrderedDict(), "por_favorecido_geral": {}, "hhi": {}, "n_fornecedores": 0}
    if not _DB.exists():
        return out
    con = sqlite3.connect(_DB)
    con.row_factory = sqlite3.Row
    try:
        q = ("SELECT numero_ob, data_pagamento, data_emissao, favorecido_cpf, favorecido_nome, valor, exercicio "
             "FROM ordens_bancarias WHERE ug_codigo=?")
        params: list = [str(ug)]
        if anos:
            q += " AND exercicio IN (%s)" % ",".join("?" * len(anos))
            params += list(anos)
        q += " ORDER BY exercicio, data_pagamento, numero_ob"
        rows = con.execute(q, params).fetchall()
    finally:
        con.close()
    if not rows:
        return out

    por_ano: "OrderedDict[int, dict]" = OrderedDict()
    forn_geral: dict = defaultdict(float)
    forn_cnpjs: set = set()
    for r in rows:
        ano = int(r["exercicio"] or 0)
        bloco = por_ano.setdefault(ano, {"n": 0, "total": 0.0, "linhas": [], "por_favorecido": defaultdict(float)})
        valor = float(r["valor"] or 0.0)
        nome = (r["favorecido_nome"] or "—").strip()
        cnpj = so_digitos(r["favorecido_cpf"] or "")
        forn_cnpjs.add(cnpj)
        data = (r["data_pagamento"] or r["data_emissao"] or "—")
        bloco["n"] += 1
        bloco["total"] += valor
        bloco["por_favorecido"][nome] += valor
        bloco["linhas"].append({"numero_ob": r["numero_ob"] or "—", "data": data,
                                "favorecido": nome, "cnpj": cnpj, "valor": valor})
        forn_geral[nome] += valor

    out["por_ano"] = por_ano
    out["anos"] = sorted(por_ano.keys())
    out["n_geral"] = sum(b["n"] for b in por_ano.values())
    out["total_geral"] = sum(b["total"] for b in por_ano.values())
    out["por_favorecido_geral"] = dict(sorted(forn_geral.items(), key=lambda kv: kv[1], reverse=True))
    out["n_fornecedores"] = len(forn_cnpjs)
    out["hhi"] = _hhi(out["por_favorecido_geral"])
    out["tem_dados"] = True
    return out


# ───────────────────────────── montagem ─────────────────────────────

def montar(orgao: Optional[str] = None, ug: Optional[str] = None,
           anos: Optional[list[int]] = None, salvar: bool = True) -> dict:
    termo = (ug or orgao or "").strip()
    cands = buscar_orgaos(termo)
    if not cands:
        return {"ok": False, "erro": f"Não encontrei órgão/UG para {termo!r}. Tente outro nome ou o código da UG."}
    cod = "".join(ch for ch in termo if ch.isdigit())
    if len(cands) == 1 or (cod and any(c["ug"] == cod for c in cands)):
        escolhido = next((c for c in cands if c["ug"] == cod), cands[0])
    else:
        opcoes = [{"n": i + 1, "ug": c["ug"], "nome": c["nome"], "total_pago": c["total_pago"], "n_obs": c["n_obs"]}
                  for i, c in enumerate(cands)]
        linhas = [f"{o['n']}) {o['nome']} (UG {o['ug']}) — R$ {moeda(o['total_pago'])} em {o['n_obs']} OBs" for o in opcoes]
        return {"ok": False, "ambiguo": True, "termo": termo, "candidatos": opcoes,
                "pergunta": f"Encontrei {len(opcoes)} órgãos para \"{termo}\". Qual deles, Mestre Jorge?\n"
                            + "\n".join(linhas) + "\n\nResponda com o número ou o código da UG."}

    ug_cod = escolhido["ug"]
    pagamentos = consultar_orgao(ug_cod, anos)
    nome = escolhido["nome"]
    # concentração geográfica dos fornecedores da UG (best-effort, sobre endereços ingeridos)
    try:
        from compliance_agent.cruzamento import cidades_de_orgao
        geo = cidades_de_orgao(ug=ug_cod, anos=anos, limite=15)
    except Exception as exc:  # noqa: BLE001
        geo = {"ok": False, "_nota": str(exc)[:120]}
    ctx = {"ug": ug_cod, "nome": nome, "data": date.today().isoformat(), "pagamentos": pagamentos,
           "alias": ugs.ALIASES.get(ug_cod, {}), "geo": geo}

    md = render_md(ctx)
    path_md = path_pdf = path_xlsx = ""
    if salvar:
        _REPORTS.mkdir(parents=True, exist_ok=True)
        base = f"inteligencia_orgao_{_slug(nome) or ug_cod}_{ctx['data']}"
        path_md = str(_REPORTS / f"{base}.md")
        Path(path_md).write_text(md, encoding="utf-8")
        try:
            path_pdf = render_pdf(ctx, str(_REPORTS / f"{base}.pdf"))
        except Exception as exc:  # noqa: BLE001
            path_pdf = ""
            ctx["_pdf_erro"] = str(exc)[:160]
        try:
            from compliance_agent.reporting import planilha
            path_xlsx = planilha.gerar(ctx, str(_REPORTS / f"{base}.xlsx"), modo="orgao")
        except Exception as exc:  # noqa: BLE001
            path_xlsx = ""
            ctx["_xlsx_erro"] = str(exc)[:160]

    return {"ok": True, "ug": ug_cod, "orgao": nome, "resumo": _resumo(ctx),
            "path_md": path_md, "path_pdf": path_pdf, "path_xlsx": path_xlsx,
            "fonte": "REAL" if pagamentos["tem_dados"] else "SEM_DADOS"}


def gerar(orgao: Optional[str] = None, ug: Optional[str] = None, anos: Optional[list[int]] = None) -> dict:
    return montar(orgao=orgao, ug=ug, anos=anos)


def parecer_orgao(ctx: dict) -> str:
    """PARECER de mérito e jurídico sobre a EXECUÇÃO do órgão (honesto, indícios a verificar)."""
    p = ctx["pagamentos"]
    if not p["tem_dados"]:
        return "Sem Ordens Bancárias para esta UG na base local — sem base para parecer de mérito."
    nome = ctx["nome"]
    total = p["total_geral"]
    hhi = p["hhi"]
    top_share = hhi.get("top_share", 0)
    top_nome, top_val = next(iter(p["por_favorecido_geral"].items()), ("—", 0))
    L: list[str] = []
    add = L.append

    add("### Análise de mérito")
    add("")
    add(f"A unidade gestora **{nome} (UG {ctx['ug']})** executou **R$ {moeda(total)}** em **{p['n_geral']} "
        f"ordens bancárias** a **{p['n_fornecedores']} fornecedores** no período. O maior recebedor, "
        f"**{top_nome}**, concentra **R$ {moeda(top_val)}** ({(top_val/(total or 1)*100):.1f}% do total), "
        f"com HHI de {hhi.get('indice')} (concentração {hhi.get('nivel').lower()}).")
    add("")
    if top_share >= 50:
        add(f"A concentração de **{top_share:.1f}%** em um único fornecedor é elevada e exige verificar se as "
            "contratações foram **competitivas** ou se houve fracionamento, dispensa/inexigibilidade reiterada "
            "ou direcionamento. Fornecedor dominante em órgão público é *red flag* clássico de cartel/captura.")
    elif top_share >= 30:
        add(f"A concentração de {top_share:.1f}% no maior fornecedor é relevante e merece exame da competitividade "
            "dos certames e do parcelamento do objeto.")
    else:
        add(f"A distribuição entre fornecedores é relativamente pulverizada (maior fatia {top_share:.1f}%), "
            "o que é um sinal positivo de competitividade — sem afastar a checagem dos maiores contratos.")
    add("")
    alias = ctx.get("alias") or {}
    if alias.get("orgao_superior"):
        add(f"**Atenção de classificação:** a UG {ctx['ug']} tem como órgão superior *{alias['orgao_superior']}*; "
            "pagamentos podem aparecer rotulados pelo órgão superior nas OBs. Confirmar a titularidade da "
            "execução evita atribuição equivocada de responsabilidade.")
        add("")

    add("### Avaliação jurídica")
    add("")
    add("- **CF/88, art. 37** — impessoalidade e moralidade na execução da despesa;")
    add("- **Lei 14.133/2021** — competitividade, vedação a direcionamento (art. 9º/11) e publicidade no PNCP (art. 94);")
    add("- **Lei 8.666/93, art. 23, §1º e art. 89** — vedação a fracionamento para fugir de modalidade;")
    add("- **Lei 4.320/64** — regularidade do empenho→liquidação→pagamento (OB);")
    add("- **TCU/ACFE** — concentração de fornecedor e pagamentos atípicos como indicadores de risco.")
    add("")
    grau = "ALTO" if top_share >= 50 else ("MÉDIO" if top_share >= 30 else "MODERADO")
    add("### Conclusão e grau de atenção")
    add("")
    add(f"**Grau de atenção recomendado: {grau}.** São **indícios a verificar**, não conclusão de "
        "irregularidade. Recomenda-se levantar contratos e processos SEI dos maiores fornecedores, conferir "
        "modalidade licitatória e checar a regularidade fiscal/sancionatória dos recebedores dominantes.")
    add("")
    add("> **Ressalva:** baseado em dados de pagamento (OB) públicos; sem exame documental dos contratos. "
        "Vigora a presunção de regularidade dos atos administrativos até prova em contrário.")
    return "\n".join(L)


def _resumo(ctx: dict) -> str:
    p = ctx["pagamentos"]
    if not p["tem_dados"]:
        return f"{ctx['nome']} (UG {ctx['ug']}): sem OBs registradas na base local."
    anos_txt = ", ".join(f"{a}: R$ {moeda(p['por_ano'][a]['total'])}" for a in p["anos"])
    top = next(iter(p["por_favorecido_geral"].items()), ("—", 0))
    return (f"{ctx['nome']} (UG {ctx['ug']}) — pagamentos {anos_txt}. Total R$ {moeda(p['total_geral'])} "
            f"em {p['n_geral']} OBs a {p['n_fornecedores']} fornecedores. Concentração HHI {p['hhi'].get('indice')} "
            f"({p['hhi'].get('nivel')}); maior recebedor: {top[0]} (R$ {moeda(top[1])}, "
            f"{(top[1]/(p['total_geral'] or 1)*100):.1f}%).")


# ───────────────────────────── render Markdown ─────────────────────────────

def _sigla_descr(nome: str) -> tuple[str, str]:
    """Separa "ITERJ — Instituto de Terras..." em ("ITERJ", "Instituto de Terras...")."""
    if "—" in nome:
        a, b = nome.split("—", 1)
        return a.strip(), b.strip()
    return nome.strip(), ""


def render_md(ctx: dict) -> str:
    p = ctx["pagamentos"]
    sigla, descr = _sigla_descr(ctx["nome"])
    L: list[str] = []
    add = L.append
    add(f"# RELATÓRIO DE INTELIGÊNCIA — {sigla}")
    add(f"### {descr or sigla}  ·  UG {ctx['ug']}")
    add("")
    add("*Execução de pagamentos · Concentração por fornecedor · Risco & Compliance*")
    add("")
    alias = ctx.get("alias") or {}
    if alias:
        add(f"> **Nota de UG:** unidade gestora {ctx['ug']} (SIAFE-Rio 2: {alias.get('siafe_rio2','—')}). "
            f"Órgão superior: {alias.get('orgao_superior','—')}. Nas Ordens Bancárias os pagamentos podem "
            f"aparecer rotulados pelo nome do órgão superior — aqui são atribuídos pela UG.")
        add("")
    add(f"**Data:** {ctx['data']}  |  **Analista:** JFN Intelligence Engine  |  **Fonte:** SIAFE/TFE-RJ (OBs — pagamento)")
    add("")
    add("---")
    add("")
    _fr = cabecalho_frescor()  # honestidade: cobertura/frescor da base no topo
    if _fr:
        add(_fr)
        add("")
    add("## SUMÁRIO EXECUTIVO")
    add("")
    add(_resumo(ctx))
    add("")
    if p["tem_dados"]:
        add("### Execução financeira — pagamentos por exercício")
        add("")
        add("| Exercício | Nº de OBs | Fornecedores | Valor pago (R$) |")
        add("|---|---:|---:|---:|")
        for a in p["anos"]:
            b = p["por_ano"][a]
            nf = len({l["cnpj"] for l in b["linhas"]})
            add(f"| {a} | {b['n']} | {nf} | {moeda(b['total'])} |")
        add(f"| **Total** | **{p['n_geral']}** | **{p['n_fornecedores']}** | **{moeda(p['total_geral'])}** |")
        add("")

    # Concentração por favorecido + HHI
    add("## 1. CONCENTRAÇÃO POR FORNECEDOR (HHI)")
    add("")
    if p["tem_dados"]:
        add(f"**HHI:** {p['hhi'].get('indice')} — concentração **{p['hhi'].get('nivel')}** "
            f"(maior fornecedor = {p['hhi'].get('top_share')}% do valor pago).")
        add("")
        add("| Fornecedor | Valor recebido (R$) | % do total |")
        add("|---|---:|---:|")
        tot = p["total_geral"] or 1
        for nome, val in list(p["por_favorecido_geral"].items())[:25]:
            add(f"| {nome} | {moeda(val)} | {val/tot*100:.1f}% |")
        add("")
        if p["hhi"].get("top_share", 0) >= 50:
            add("> 🔴 **Red flag (ACFE):** um único fornecedor concentra ≥50% dos pagamentos do órgão — "
                "verificar competitividade das contratações (Art. 37 CF/88; Lei 14.133/2021).")
            add("")
    else:
        add("_Sem OBs para esta UG._")
        add("")

    # Concentração GEOGRÁFICA dos fornecedores (cidade-sede)
    geo = ctx.get("geo") or {}
    add("## 1-B. CONCENTRAÇÃO GEOGRÁFICA DOS FORNECEDORES (CIDADE-SEDE)")
    add("")
    add("> Em que **cidades** estão sediados os fornecedores que este órgão paga. Concentração alta numa "
        "cidade pequena/distante da atuação do órgão é red flag clássico (empresas de fachada/direcionamento — "
        "art. 337-F CP). Cruza as OBs com o endereço (Receita/BrasilAPI) do CNPJ.")
    add("")
    if geo.get("ok"):
        add(f"**Cobertura:** {geo.get('cobertura_valor',0)*100:.0f}% do valor pago e "
            f"{geo.get('cobertura_forn',0)*100:.0f}% dos fornecedores têm endereço ingerido "
            "(o ranking abaixo é sobre essa fração).")
        add("")
        add("| Cidade/UF | Fornecedores | OBs | Valor recebido (R$) | % (da fração conhecida) |")
        add("|---|---:|---:|---:|---:|")
        for c in geo["cidades"]:
            cid = f"{c['cidade']}/{c['uf']}" if c.get("uf") else c["cidade"]
            add(f"| {cid} | {c['n_fornecedores']} | {c['n_obs']} | {moeda(c['total_pago'])} | {c['pct']:.1f}% |")
        add("")
        top = geo["cidades"][0]
        if top["pct"] >= 50 and (top.get("uf") or "") and top["cidade"]:
            add(f"> 🟡 **Indício:** {top['pct']:.0f}% do valor (na fração com endereço) vai a fornecedores "
                f"sediados em **{top['cidade']}/{top['uf']}** — verificar se a concentração geográfica é "
                "compatível com o objeto e a competitividade das contratações.")
            add("")
        if geo.get("_nota"):
            add(f"> ℹ️ {geo['_nota']}")
            add("")
    else:
        _motivo = geo.get("_nota") or "sem endereços ingeridos para os fornecedores desta UG"
        add(f"_Concentração geográfica indisponível ({_motivo}). "
            "Rode `python -m compliance_agent.rede_societaria --ingerir-top 2000`._")
        add("")

    # Tabelas de OBs por ano (pagamentos individuais a cada fornecedor)
    add("## 2. PAGAMENTOS (ORDENS BANCÁRIAS) POR ANO")
    add("")
    add("> Por exercício, as **maiores OBs** (materiais) e o fornecedor; a **lista completa** de cada "
        "pagamento está na **planilha XLSX** deste relatório. OB = pagamento definitivo; OBs de R$ 0,00 são "
        "estornos/regularizações.")
    add("")
    if p["tem_dados"]:
        TOP_OB_ANO = 12  # padrão de due diligence: destacar o material; detalhe completo na planilha
        for a in p["anos"]:
            b = p["por_ano"][a]
            add(f"### Exercício {a} — {b['n']} OBs — Total pago: R$ {moeda(b['total'])}")
            add("")
            maiores = sorted(b["linhas"], key=lambda ln: -(ln.get("valor") or 0))[:TOP_OB_ANO]
            add("| # | Nº OB | Data | Fornecedor (CNPJ) | Valor (R$) |")
            add("|---:|---|---|---|---:|")
            for i, ln in enumerate(maiores, 1):
                forn = f"{ln['favorecido']} ({fmt_cnpj(ln['cnpj'])})" if ln["cnpj"] else ln["favorecido"]
                add(f"| {i} | {ln['numero_ob']} | {ln['data']} | {forn} | {moeda(ln['valor'])} |")
            add(f"| | | | **Total {a} ({b['n']} OBs)** | **{moeda(b['total'])}** |")
            if b["n"] > len(maiores):
                add("")
                add(f"> _{len(maiores)} maiores de {b['n']} OBs do exercício — lista completa na planilha XLSX._")
            add("")
    else:
        add("_Sem OBs para esta UG._")
        add("")

    # Parecer escrito do JFN
    add("## 3. ANÁLISE JURÍDICA E DE MÉRITO — PARECER PRELIMINAR DO JFN")
    add("")
    add(parecer_orgao(ctx))
    add("")

    add("## 4. RECOMENDAÇÕES")
    add("")
    add("- Cruzar os maiores fornecedores (Seção 1) com seus contratos e processos SEI.")
    add("- Verificar a modalidade de contratação dos pagamentos concentrados (pregão/dispensa/inexigibilidade).")
    add("- Monitorar pagamentos atípicos (fim de exercício, valores redondos repetidos).")
    add("")
    add("## 5. REFERÊNCIAS")
    add("")
    add("- **Dados:** SIAFE-Rio / Transparência Fiscal RJ (OBs) — `data/compliance.db`; mapa de UG `data/ug_canonico.json`.")
    add("- **Normas:** Lei 14.133/2021; Lei 8.666/93; CF/88 Art. 37; metodologia TCU; ACFE Report to the Nations.")
    add("")
    add(f"_Gerado pelo JFN Intelligence Engine em {ctx['data']}. Não substitui análise jurídica especializada._")
    add("")
    return "\n".join(L)


# ───────────────────────────── render PDF ─────────────────────────────

def render_pdf(ctx: dict, destino: str) -> str:
    from fpdf import FPDF
    p = ctx["pagamentos"]
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf._fam, pdf._uni = _registrar_fonte(pdf)
    pdf.add_page()

    def _t(s: str) -> str:
        s = s or ""
        if getattr(pdf, "_uni", False):
            return s
        for a, b in (("—", "-"), ("–", "-"), ("₂", "2"), ("•", "-"), ("·", "-")):
            s = s.replace(a, b)
        return s.encode("latin-1", "replace").decode("latin-1")

    pdf.set_fill_color(20, 30, 50); pdf.set_text_color(255, 255, 255)
    pdf.set_font(pdf._fam, "B", 15)
    pdf.cell(0, 13, _t("RELATÓRIO DE INTELIGÊNCIA DE ÓRGÃO"), fill=True, ln=True, align="C")
    pdf.set_font(pdf._fam, "", 9); pdf.set_fill_color(45, 60, 90)
    pdf.cell(0, 7, _t("Execução de pagamentos · Concentração por fornecedor · Risco"), fill=True, ln=True, align="C")
    pdf.cell(0, 7, _t(f"JFN Intelligence Engine  |  {ctx['data']}"), fill=True, ln=True, align="C")
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "B", 14)
    _mc(pdf, 8, _t(f"{ctx['nome']}  ·  UG {ctx['ug']}"))
    pdf.ln(1); pdf.set_font(pdf._fam, "", 9)
    _mc(pdf, 5, _t(_resumo(ctx)))

    if p["tem_dados"]:
        pdf.ln(3); pdf.set_font(pdf._fam, "B", 12)
        pdf.cell(0, 8, _t("Pagamentos por exercício"), ln=True)
        _tab_header(pdf, [("Exercício", 36), ("Nº OBs", 26), ("Fornec.", 26), ("Valor pago (R$)", 62)])
        pdf.set_font(pdf._fam, "", 9)
        for a in p["anos"]:
            b = p["por_ano"][a]
            nf = len({l["cnpj"] for l in b["linhas"]})
            _tab_row(pdf, [(str(a), 36, "L"), (str(b["n"]), 26, "R"), (str(nf), 26, "R"), (moeda(b["total"]), 62, "R")])
        pdf.set_font(pdf._fam, "B", 9)
        _tab_row(pdf, [("Total", 36, "L"), (str(p["n_geral"]), 26, "R"), (str(p["n_fornecedores"]), 26, "R"),
                       (moeda(p["total_geral"]), 62, "R")])

        # Concentração por fornecedor
        pdf.add_page(); pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
        pdf.cell(0, 9, _t("Concentração por fornecedor (HHI)"), ln=True)
        pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 9)
        pdf.cell(0, 6, _t(f"HHI {p['hhi'].get('indice')} — {p['hhi'].get('nivel')} "
                          f"(maior fornecedor = {p['hhi'].get('top_share')}%)"), ln=True); pdf.ln(1)
        _tab_header(pdf, [("Fornecedor", 130), ("Valor (R$)", 36), ("%", 16)])
        pdf.set_font(pdf._fam, "", 8)
        tot = p["total_geral"] or 1
        for nome, val in list(p["por_favorecido_geral"].items())[:30]:
            _tab_row(pdf, [(_t(nome)[:86], 130, "L"), (moeda(val), 36, "R"), (f"{val/tot*100:.1f}", 16, "R")], h=5)

        # OBs por ano
        for a in p["anos"]:
            b = p["por_ano"][a]
            pdf.add_page(); pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
            pdf.cell(0, 9, _t(f"Pagamentos (OBs) — exercício {a}"), ln=True)
            pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 9)
            _maiores = sorted(b["linhas"], key=lambda ln: -(ln.get("valor") or 0))[:12]
            _nota = f"{b['n']} OBs — Total: R$ {moeda(b['total'])}" + (
                f"  ·  {len(_maiores)} maiores abaixo; lista completa na planilha XLSX" if b["n"] > len(_maiores) else "")
            pdf.cell(0, 6, _t(_nota), ln=True); pdf.ln(1)
            _tab_header(pdf, [("#", 9), ("Nº OB", 26), ("Data", 22), ("Fornecedor", 97), ("Valor (R$)", 36)])
            pdf.set_font(pdf._fam, "", 7)
            for i, ln in enumerate(_maiores, 1):
                _tab_row(pdf, [(str(i), 9, "R"), (_t(ln["numero_ob"]), 26, "L"), (_t(ln["data"])[:10], 22, "L"),
                               (_t(ln["favorecido"])[:60], 97, "L"), (moeda(ln["valor"]), 36, "R")], h=4.5)
            pdf.set_font(pdf._fam, "B", 8)
            _tab_row(pdf, [("", 9, "L"), ("", 26, "L"), ("", 22, "L"), (f"Total {a}", 97, "R"),
                           (moeda(b["total"]), 36, "R")], h=5)

    # Parecer jurídico e de mérito
    pdf.add_page()
    pdf.set_font(pdf._fam, "B", 14); pdf.set_text_color(20, 30, 50)
    pdf.cell(0, 10, _t("Análise Jurídica e de Mérito — Parecer Preliminar do JFN"), ln=True)
    pdf.set_text_color(0, 0, 0)
    _render_parecer_pdf(pdf, _t, parecer_orgao(ctx))

    pdf.ln(3); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(120, 120, 120)
    _mc(pdf, 4, _t("Gerado pelo JFN Intelligence Engine. Não substitui análise jurídica especializada."))

    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(destino)
    return destino


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Uso: python -m compliance_agent.reporting.inteligencia_orgao <órgão/UG> [ano1 ano2 ...]")
        sys.exit(1)
    anos_cli = [int(a) for a in args if a.isdigit() and len(a) == 4]
    termo_cli = " ".join(a for a in args if not (a.isdigit() and len(a) == 4)).strip()
    res = gerar(orgao=termo_cli, anos=anos_cli or None)
    print(json.dumps({k: v for k, v in res.items() if k != "resumo"}, ensure_ascii=False, indent=2))
    print("\nRESUMO:", res.get("resumo", ""))
