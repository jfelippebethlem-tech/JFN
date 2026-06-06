# -*- coding: utf-8 -*-
"""
RELATÓRIO DE INTELIGÊNCIA DE FORNECEDOR — orquestrador de 1 chamada.

É o motor do comando `/relatorio` do Yoda. Dado um CNPJ **ou** um nome de empresa, monta um
relatório de due diligence (padrão Kroll/Deloitte, ver CLAUDE.md) e o salva em `reports/` como
`.md` e `.pdf`.

USO (CLI, para IA fraca rodar):
    cd ~/JFN
    .venv/bin/python -m compliance_agent.reporting.inteligencia "MGS Clean"
    .venv/bin/python -m compliance_agent.reporting.inteligencia 19.088.605/0001-04 2023 2024 2025 2026

USO (API, chamado pelo server.py):
    from compliance_agent.reporting.inteligencia import montar
    res = await montar(cnpj="19088605000104")     # async
    # res = {ok, cnpj, empresa, risco, score, resumo, path_md, path_pdf, fonte}

FONTES DE DADO (e honestidade — princípio do JFN: Empenho ≠ Pagamento):
  - **OBs pagas** (`data/compliance.db` → ordens_bancarias): dado REAL de PAGAMENTO (Ordem Bancária = fonte
    de verdade). É a espinha financeira do relatório, com **uma tabela por ano** (2023, 2024, 2025, 2026).
  - **Contratos** (`data/compliance.db` → contratos): carteira oficial coletada do SIAFE.
  - **Perfil cadastral / sanções / rede societária / sinais de risco**: `relatorio_riscos.gerar_relatorio_risco`
    (APIs públicas — Receita/PNCP/CEIS-CNEP). É best-effort: se o egress da VM falhar, o relatório sai assim
    mesmo, marcando a seção como INDISPONÍVEL (nunca inventa número).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import sys
from collections import OrderedDict, defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
_DATA = Path(os.environ.get("JFN_DATA_DIR", _ROOT / "data"))
_DB = _DATA / "compliance.db"
_REPORTS = _ROOT / "reports"
_REGISTRY = _DATA / "empresas_target.json"

# timeout (s) para o enriquecimento via APIs públicas (egress da VM é lento).
# MANTER ABAIXO do timeout do `terminal` do Yoda (60s) — senão o curl morre antes do relatório retornar.
# Se as fontes externas (Receita/PNCP/sanções) demorarem, o relatório sai assim mesmo com os dados REAIS
# locais (OBs/contratos) e marca o enriquecimento como INDISPONÍVEL.
_ENRIQUECE_TIMEOUT = float(os.environ.get("JFN_RELATORIO_ENRIQUECE_TIMEOUT", "35"))


# ───────────────────────────── helpers de formatação ─────────────────────────────

def so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def fmt_cnpj(c: str) -> str:
    c = so_digitos(c)
    if len(c) != 14:
        return c
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


def moeda(v) -> str:
    """1234567.89 -> '1.234.567,89' (padrão BR, sempre 2 casas)."""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:40]


# ───────────────────────────── resolução de empresa ─────────────────────────────

def _carregar_registro() -> list[dict]:
    try:
        return json.loads(_REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return []


def _nome_por_cnpj(cnpj: str) -> str:
    """Melhor nome conhecido para um CNPJ (registro > empresas > OBs)."""
    cnpj = so_digitos(cnpj)
    for e in _carregar_registro():
        if so_digitos(e.get("cnpj", "")) == cnpj:
            return e.get("nome", "")
    if _DB.exists():
        con = sqlite3.connect(_DB)
        try:
            r = con.execute("SELECT razao_social FROM empresas WHERE cnpj=?", (cnpj,)).fetchone()
            if r and r[0]:
                return r[0]
            r = con.execute(
                "SELECT favorecido_nome FROM ordens_bancarias WHERE favorecido_cpf=? AND favorecido_nome IS NOT NULL LIMIT 1",
                (cnpj,)).fetchone()
            if r and r[0]:
                return r[0]
        except Exception:
            pass
        finally:
            con.close()
    return ""


def buscar_candidatos(termo: str, limite: int = 8) -> list[dict]:
    """
    Resolve por CNPJ OU por nome (inclusive PARCIAL). Retorna lista de candidatos
    [{cnpj, nome, fonte, total_pago, n_obs}], rankeados por valor pago (empresas com dados de OB
    aparecem primeiro — são as mais relevantes para auditoria). Lista vazia = nada encontrado.
    """
    termo = (termo or "").strip()
    dig = so_digitos(termo)
    if len(dig) == 14:
        return [{"cnpj": dig, "nome": _nome_por_cnpj(dig), "fonte": "cnpj", "total_pago": 0.0, "n_obs": 0}]

    alvo = termo.lower().strip()
    if not alvo:
        return []

    cands: "OrderedDict[str, dict]" = OrderedDict()

    def _add(cnpj, nome, fonte):
        cnpj = so_digitos(cnpj)
        if not cnpj:
            return
        if cnpj not in cands:
            cands[cnpj] = {"cnpj": cnpj, "nome": nome or "", "fonte": fonte, "total_pago": 0.0, "n_obs": 0}
        elif nome and not cands[cnpj]["nome"]:
            cands[cnpj]["nome"] = nome

    # 1) registro curado
    for e in _carregar_registro():
        if alvo in (e.get("nome", "").lower()):
            _add(e.get("cnpj", ""), e.get("nome", ""), "registro")

    if _DB.exists():
        con = sqlite3.connect(_DB)
        con.row_factory = sqlite3.Row
        try:
            # 2) tabela empresas (perfil cadastral)
            for r in con.execute(
                "SELECT cnpj, razao_social FROM empresas WHERE lower(razao_social) LIKE ? LIMIT 50",
                (f"%{alvo}%",)):
                _add(r["cnpj"], r["razao_social"], "empresas_db")
            # 3) nomes nas OBs (fonte mais rica) — agrega valor pago para rankear
            for r in con.execute(
                "SELECT favorecido_cpf cnpj, MAX(favorecido_nome) nome, COUNT(*) n, "
                "ROUND(SUM(valor),2) total FROM ordens_bancarias "
                "WHERE lower(favorecido_nome) LIKE ? AND favorecido_cpf IS NOT NULL "
                "GROUP BY favorecido_cpf ORDER BY total DESC LIMIT 50",
                (f"%{alvo}%",)):
                _add(r["cnpj"], r["nome"], "obs")
            # preenche métricas de OB para todos os candidatos
            for cnpj, c in cands.items():
                r = con.execute(
                    "SELECT COUNT(*) n, ROUND(SUM(valor),2) total FROM ordens_bancarias WHERE favorecido_cpf=?",
                    (cnpj,)).fetchone()
                c["n_obs"] = int(r["n"] or 0)
                c["total_pago"] = float(r["total"] or 0.0)
        except Exception:
            pass
        finally:
            con.close()

    ordenados = sorted(cands.values(), key=lambda c: (c["total_pago"], c["n_obs"]), reverse=True)
    return ordenados[:limite]


def resolver_empresa(termo: str) -> dict:
    """Compat: retorna o melhor candidato único {cnpj, nome, fonte} (ou cnpj='')."""
    c = buscar_candidatos(termo, limite=1)
    return c[0] if c else {"cnpj": "", "nome": termo, "fonte": "nao_resolvido"}


# ───────────────────────────── consultas compliance.db ─────────────────────────────

def consultar_pagamentos(cnpj: str, anos: Optional[list[int]] = None) -> dict:
    """
    OBs pagas ao fornecedor (ordens_bancarias). Retorna estrutura por ano com as linhas individuais.

    {
      "tem_dados": bool,
      "anos": [2023, 2024, 2025, 2026],
      "total_geral": float, "n_geral": int,
      "por_ano": { 2023: {"n": int, "total": float, "linhas": [ {numero_ob,data,orgao,valor}, ... ],
                          "por_orgao": {orgao: total, ...}}, ... },
      "por_orgao_geral": {orgao: total, ...},
      "hhi": {"indice": float, "nivel": str},
    }
    """
    out = {"tem_dados": False, "anos": [], "total_geral": 0.0, "n_geral": 0,
           "por_ano": OrderedDict(), "por_orgao_geral": {}, "hhi": {}}
    if not _DB.exists():
        return out
    cnpj = so_digitos(cnpj)
    con = sqlite3.connect(_DB)
    con.row_factory = sqlite3.Row
    try:
        q = ("SELECT numero_ob, data_pagamento, data_emissao, ug_codigo, ug_nome, valor, exercicio "
             "FROM ordens_bancarias WHERE favorecido_cpf=?")
        params: list = [cnpj]
        if anos:
            q += " AND exercicio IN (%s)" % ",".join("?" * len(anos))
            params += list(anos)
        q += " ORDER BY exercicio, data_pagamento, numero_ob"
        rows = con.execute(q, params).fetchall()
    finally:
        con.close()
    if not rows:
        return out

    from compliance_agent import ugs  # mapa canônico de UG (corrige p.ex. 133100 -> ITERJ)

    por_ano: "OrderedDict[int, dict]" = OrderedDict()
    orgao_geral: dict = defaultdict(float)
    for r in rows:
        ano = int(r["exercicio"] or 0)
        bloco = por_ano.setdefault(ano, {"n": 0, "total": 0.0, "linhas": [], "por_orgao": defaultdict(float)})
        valor = float(r["valor"] or 0.0)
        # rótulo canônico da unidade gestora (corrige o nome do órgão superior nas OBs)
        orgao = ugs.rotulo(r["ug_codigo"], r["ug_nome"] or "—")
        data = (r["data_pagamento"] or r["data_emissao"] or "—")
        bloco["n"] += 1
        bloco["total"] += valor
        bloco["por_orgao"][orgao] += valor
        bloco["linhas"].append({"numero_ob": r["numero_ob"] or "—", "data": data, "orgao": orgao, "valor": valor})
        orgao_geral[orgao] += valor

    for ano, b in por_ano.items():
        b["por_orgao"] = dict(sorted(b["por_orgao"].items(), key=lambda kv: kv[1], reverse=True))
    out["por_ano"] = por_ano
    out["anos"] = sorted(por_ano.keys())
    out["n_geral"] = sum(b["n"] for b in por_ano.values())
    out["total_geral"] = sum(b["total"] for b in por_ano.values())
    out["por_orgao_geral"] = dict(sorted(orgao_geral.items(), key=lambda kv: kv[1], reverse=True))
    out["hhi"] = _hhi(out["por_orgao_geral"])
    out["tem_dados"] = True
    return out


def _hhi(por_orgao: dict) -> dict:
    """Índice Herfindahl-Hirschman da concentração por órgão (0..10000)."""
    total = sum(v for v in por_orgao.values() if v > 0)
    if total <= 0:
        return {"indice": 0.0, "nivel": "—", "top_share": 0.0}
    indice = sum((v / total * 100) ** 2 for v in por_orgao.values() if v > 0)
    if indice < 1500:
        nivel = "BAIXA"
    elif indice < 2500:
        nivel = "MODERADA"
    else:
        nivel = "ALTA"
    top = max(por_orgao.values())
    return {"indice": round(indice, 1), "nivel": nivel, "top_share": round(top / total * 100, 1)}


def consultar_contratos(cnpj: str) -> dict:
    """Contratos oficiais (compliance.db). Retorna {n, total, linhas[...]}."""
    out = {"n": 0, "total": 0.0, "linhas": []}
    if not _DB.exists():
        return out
    cnpj = so_digitos(cnpj)
    con = sqlite3.connect(_DB)
    con.row_factory = sqlite3.Row
    try:
        emp = con.execute("SELECT id FROM empresas WHERE cnpj=?", (cnpj,)).fetchone()
        if not emp:
            return out
        rows = con.execute(
            "SELECT numero, objeto, orgao_contrat, valor_total, data_assinatura, status "
            "FROM contratos WHERE empresa_id=? ORDER BY valor_total DESC", (emp["id"],),
        ).fetchall()
    finally:
        con.close()
    for r in rows:
        out["linhas"].append({
            "numero": r["numero"] or "—", "objeto": r["objeto"] or "—",
            "orgao": r["orgao_contrat"] or "—", "valor": float(r["valor_total"] or 0.0),
            "assinatura": r["data_assinatura"] or "—", "status": r["status"] or "—",
        })
    out["n"] = len(out["linhas"])
    out["total"] = sum(l["valor"] for l in out["linhas"])
    return out


# ───────────────────────────── enriquecimento (APIs públicas) ─────────────────────────────

async def _enriquecer(cnpj: str) -> dict:
    """gerar_relatorio_risco best-effort. Nunca derruba o relatório. fonte: REAL|INDISPONIVEL."""
    try:
        from relatorio_riscos import gerar_relatorio_risco
        res = await asyncio.wait_for(
            gerar_relatorio_risco(cnpj, formato="md", salvar=False), timeout=_ENRIQUECE_TIMEOUT
        )
        if res.get("ok"):
            res["_fonte"] = "REAL"
            return res
        return {"ok": False, "_fonte": "INDISPONIVEL", "_motivo": res.get("erro", "falha")}
    except asyncio.TimeoutError:
        return {"ok": False, "_fonte": "INDISPONIVEL", "_motivo": f"timeout {_ENRIQUECE_TIMEOUT:.0f}s (egress lento)"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "_fonte": "INDISPONIVEL", "_motivo": str(exc)[:120]}


# ───────────────────────────── montagem do relatório ─────────────────────────────

async def montar(cnpj: Optional[str] = None, empresa: Optional[str] = None,
                 anos: Optional[list[int]] = None, salvar: bool = True) -> dict:
    """Monta o relatório de inteligência. Retorna dict (ver docstring do módulo)."""
    termo = (cnpj or empresa or "").strip()
    candidatos = buscar_candidatos(termo)
    if not candidatos:
        return {"ok": False, "erro": f"Não encontrei nenhuma empresa para {termo!r}. "
                                     f"Tente outro nome (parcial serve) ou o CNPJ.", "empresa": termo}

    # decide se pode escolher sozinho, ou se precisa perguntar ao Mestre Jorge (via Yoda)
    alvo = termo.lower().strip()
    e_cnpj = len(so_digitos(termo)) == 14
    exatos = [c for c in candidatos if (c["nome"] or "").lower().strip() == alvo]
    if e_cnpj or len(candidatos) == 1:
        escolhido = candidatos[0]
    elif len(exatos) == 1:
        escolhido = exatos[0]
    else:
        # AMBÍGUO — devolve a dúvida para o Yoda perguntar ao Mestre Jorge
        opcoes = [{
            "n": i + 1, "cnpj": c["cnpj"], "cnpj_fmt": fmt_cnpj(c["cnpj"]),
            "nome": c["nome"] or "(sem nome)",
            "total_pago": c["total_pago"], "n_obs": c["n_obs"],
        } for i, c in enumerate(candidatos)]
        linhas = [f"{o['n']}) {o['nome']} — CNPJ {o['cnpj_fmt']}"
                  + (f" — R$ {moeda(o['total_pago'])} pagos em {o['n_obs']} OBs" if o["n_obs"] else " — sem OBs na base")
                  for o in opcoes]
        pergunta = (f"Encontrei {len(opcoes)} empresas para \"{termo}\". Qual delas, Mestre Jorge?\n"
                    + "\n".join(linhas)
                    + "\n\nResponda com o número ou o CNPJ.")
        return {"ok": False, "ambiguo": True, "termo": termo, "candidatos": opcoes, "pergunta": pergunta}

    cnpj_d = escolhido["cnpj"]
    resolv = escolhido

    pagamentos = consultar_pagamentos(cnpj_d, anos)
    contratos = consultar_contratos(cnpj_d)
    enriq = await _enriquecer(cnpj_d)

    nome = (enriq.get("empresa") or resolv["nome"] or "").strip() or fmt_cnpj(cnpj_d)
    risco = enriq.get("risco", "—")
    score = enriq.get("score", 0)

    fonte_global = "REAL" if pagamentos["tem_dados"] else "SEM_DADOS_OB"
    contexto = {
        "cnpj": cnpj_d, "cnpj_fmt": fmt_cnpj(cnpj_d), "nome": nome,
        "data": date.today().isoformat(), "risco": risco, "score": score,
        "pagamentos": pagamentos, "contratos": contratos, "enriq": enriq,
        "fonte_enriq": enriq.get("_fonte", "INDISPONIVEL"),
    }

    md = render_md(contexto)
    path_md = path_pdf = path_xlsx = ""
    if salvar:
        _REPORTS.mkdir(parents=True, exist_ok=True)
        base = f"inteligencia_{_slug(nome) or cnpj_d}_{contexto['data']}"
        path_md = str(_REPORTS / f"{base}.md")
        Path(path_md).write_text(md, encoding="utf-8")
        try:
            path_pdf = render_pdf(contexto, str(_REPORTS / f"{base}.pdf"))
        except Exception as exc:  # noqa: BLE001
            path_pdf = ""
            contexto["_pdf_erro"] = str(exc)[:160]
        try:
            from compliance_agent.reporting import planilha
            path_xlsx = planilha.gerar(contexto, str(_REPORTS / f"{base}.xlsx"), modo="fornecedor")
        except Exception as exc:  # noqa: BLE001
            path_xlsx = ""
            contexto["_xlsx_erro"] = str(exc)[:160]

    return {
        "ok": True, "cnpj": cnpj_d, "cnpj_fmt": fmt_cnpj(cnpj_d), "empresa": nome,
        "risco": risco, "score": score,
        "resumo": _resumo_executivo(contexto),
        "path_md": path_md, "path_pdf": path_pdf, "path_xlsx": path_xlsx,
        "fonte": fonte_global, "fonte_enriq": contexto["fonte_enriq"],
    }


def gerar(cnpj: Optional[str] = None, empresa: Optional[str] = None,
          anos: Optional[list[int]] = None, salvar: bool = True) -> dict:
    """Wrapper síncrono para CLI/uso fora de loop async."""
    return asyncio.run(montar(cnpj=cnpj, empresa=empresa, anos=anos, salvar=salvar))


def _resumo_executivo(ctx: dict) -> str:
    p = ctx["pagamentos"]
    linhas = [f"{ctx['nome']} (CNPJ {ctx['cnpj_fmt']})"]
    if p["tem_dados"]:
        anos_txt = ", ".join(f"{a}: R$ {moeda(p['por_ano'][a]['total'])}" for a in p["anos"])
        linhas.append(f"Pagamentos (OBs) — {anos_txt}.")
        linhas.append(f"Total pago no período: R$ {moeda(p['total_geral'])} em {p['n_geral']} OBs, "
                      f"{len(p['por_orgao_geral'])} órgãos. Concentração (HHI): {p['hhi'].get('indice')} "
                      f"({p['hhi'].get('nivel')}; maior órgão = {p['hhi'].get('top_share')}%).")
    else:
        linhas.append("Sem OBs pagas registradas na base local para este CNPJ.")
    if ctx["contratos"]["n"]:
        linhas.append(f"Carteira de contratos (SIAFE): {ctx['contratos']['n']} contratos, "
                      f"R$ {moeda(ctx['contratos']['total'])}.")
    if ctx["risco"] not in ("—", None):
        linhas.append(f"Rating de risco corporativo: {ctx['risco']} (score {ctx['score']}/100).")
    return " ".join(linhas)


# ───────────────────────────── render Markdown (11 seções) ─────────────────────────────

def render_md(ctx: dict) -> str:
    p = ctx["pagamentos"]
    L: list[str] = []
    add = L.append

    add(f"# RELATÓRIO DE INTELIGÊNCIA DE FORNECEDOR")
    add(f"### {ctx['nome']}")
    add("")
    add("*Due Diligence de Integridade · Exposição Financeira · Risco & Compliance*")
    add("")
    add(f"**CNPJ:** {ctx['cnpj_fmt']}  |  **Data:** {ctx['data']}  |  **Analista:** JFN Intelligence Engine")
    add(f"**Metodologia:** due diligence de integridade (padrão Kroll/Deloitte) · matriz de risco TCU P×I · OB = pagamento (fonte de verdade)")
    add(f"**Classificação de fonte:** OBs/Contratos = **REAL** (SIAFE/TFE) · Perfil/Sanções/Rede = **{ctx['fonte_enriq']}**")
    add("")
    add("---")
    add("")

    # 1. Sumário executivo
    add("## SUMÁRIO EXECUTIVO")
    add("")
    add(_resumo_executivo(ctx))
    add("")
    if p["tem_dados"]:
        add("### Exposição financeira — pagamentos por exercício")
        add("")
        add("| Exercício | Nº de OBs | Valor pago (R$) |")
        add("|---|---:|---:|")
        for a in p["anos"]:
            b = p["por_ano"][a]
            add(f"| {a} | {b['n']} | {moeda(b['total'])} |")
        add(f"| **Total** | **{p['n_geral']}** | **{moeda(p['total_geral'])}** |")
        add("")

    # 2. Perfil cadastral
    add("## 1. PERFIL CADASTRAL")
    add("")
    emp = (ctx["enriq"].get("dados") or {}).get("empresa") if ctx["enriq"].get("ok") else None
    if emp:
        campos = [
            ("Razão social", emp.get("razao_social")), ("Situação", emp.get("situacao")),
            ("Data de abertura", emp.get("data_abertura")), ("Porte", emp.get("porte")),
            ("Natureza jurídica", emp.get("natureza_juridica")), ("Capital social", f"R$ {moeda(emp.get('capital_social'))}"),
            ("CNAE principal", emp.get("cnae_principal")), ("Município/UF", f"{emp.get('municipio','—')}/{emp.get('uf','—')}"),
        ]
        for k, v in campos:
            add(f"- **{k}:** {v or '—'}")
        socios = emp.get("socios") or []
        if socios:
            add("")
            add("**Quadro societário:**")
            for s in socios[:15]:
                add(f"- {s.get('nome','—')} — {s.get('qualificacao','—')} (entrada: {s.get('data_entrada','—')})")
    else:
        add(f"> ⚠️ Perfil cadastral **{ctx['fonte_enriq']}** "
            f"({ctx['enriq'].get('_motivo','enriquecimento não disponível')}). "
            f"Os dados financeiros abaixo (OBs/contratos) são REAIS e independem desta seção.")
    add("")

    # 3. Pagamentos (OBs) por ano — TABELA POR ANO (requisito do Mestre Jorge)
    add("## 2. PAGAMENTOS (ORDENS BANCÁRIAS) POR ANO")
    add("")
    add("> Fonte: SIAFE/TFE-RJ (Ordem Bancária = dado **definitivo de pagamento**). Uma tabela por exercício, "
        "com os pagamentos individuais. Pode haver mais de 12 OBs/ano. OBs com valor R$ 0,00 são estornos/"
        "regularizações e entram na contagem, mas não somam ao total.")
    add("")
    if p["tem_dados"]:
        for a in p["anos"]:
            b = p["por_ano"][a]
            add(f"### Exercício {a} — {b['n']} OBs — Total pago: R$ {moeda(b['total'])}")
            add("")
            add("| # | Nº OB | Data pagamento | Órgão (UG) | Valor (R$) |")
            add("|---:|---|---|---|---:|")
            for i, ln in enumerate(b["linhas"], 1):
                add(f"| {i} | {ln['numero_ob']} | {ln['data']} | {ln['orgao']} | {moeda(ln['valor'])} |")
            add(f"| | | | **Total {a}** | **{moeda(b['total'])}** |")
            add("")
    else:
        add("_Sem OBs registradas na base local para este CNPJ._")
        add("")

    # 4. Concentração por órgão + HHI
    add("## 3. CONCENTRAÇÃO POR ÓRGÃO CONTRATANTE (HHI)")
    add("")
    if p["tem_dados"]:
        add(f"**HHI:** {p['hhi'].get('indice')} — concentração **{p['hhi'].get('nivel')}** "
            f"(maior órgão = {p['hhi'].get('top_share')}% do valor pago).")
        add("")
        add("| Órgão (UG) | Valor pago (R$) | % do total |")
        add("|---|---:|---:|")
        tot = p["total_geral"] or 1
        for org, val in list(p["por_orgao_geral"].items()):
            add(f"| {org} | {moeda(val)} | {val/tot*100:.1f}% |")
        add("")
        if p["hhi"].get("top_share", 0) >= 60:
            add("> 🔴 **Red flag (ACFE):** concentração ≥60% em um único órgão sem justificativa técnica "
                "merece verificação (isonomia/impessoalidade — Art. 37 CF/88).")
            add("")
    else:
        add("_Indisponível sem OBs._")
        add("")

    # 5. Carteira de contratos
    add("## 4. CARTEIRA DE CONTRATOS (SIAFE)")
    add("")
    c = ctx["contratos"]
    if c["n"]:
        add(f"**{c['n']} contratos** — valor total declarado: R$ {moeda(c['total'])}.")
        add("")
        add("| Nº | Objeto | Órgão | Valor (R$) | Assinatura | Situação |")
        add("|---|---|---|---:|---|---|")
        for ln in c["linhas"]:
            obj = (ln["objeto"] or "—")[:60]
            add(f"| {ln['numero']} | {obj} | {ln['orgao']} | {moeda(ln['valor'])} | {ln['assinatura']} | {ln['status']} |")
        add("")
    else:
        add("_Nenhum contrato oficial vinculado na base local._")
        add("")

    # 6. Sinais de risco (do enriquecimento)
    add("## 5. SINAIS DE RISCO CORPORATIVO")
    add("")
    if ctx["enriq"].get("ok"):
        add(f"**Rating:** {ctx['risco']} (score {ctx['score']}/100).")
        add("")
        for s in (ctx["enriq"].get("sinais") or [])[:30]:
            nivel = s.get("nivel", "")
            emoji = {"ALTO": "🔴", "MÉDIO": "🟡", "BAIXO": "🟢"}.get(nivel, "•")
            desc = s.get("descricao", "")
            det = s.get("detalhe", "")
            add(f"- {emoji} **{nivel}** — {desc}{(' — ' + det) if det else ''}")
        add("")
    else:
        add(f"> Sinais corporativos **{ctx['fonte_enriq']}** ({ctx['enriq'].get('_motivo','—')}).")
        add("")

    # 7. Verificação de sanções
    add("## 6. VERIFICAÇÃO EM LISTAS RESTRITIVAS (CEIS/CNEP/CEPIM)")
    add("")
    sanc = (ctx["enriq"].get("dados") or {}).get("sancoes") if ctx["enriq"].get("ok") else None
    if sanc:
        if sanc.get("verificado"):
            n = sanc.get("n_sancoes", 0)
            add(("✅ Nenhuma sanção identificada." if n == 0 else f"🔴 {n} sanção(ões) identificada(s)!"))
        else:
            add(f"> Verificação não realizada: {sanc.get('motivo','—')}.")
    else:
        add(f"> **{ctx['fonte_enriq']}**.")
    add("")

    # 8. Matriz de risco TCU P×I (qualitativa, a partir do que temos)
    add("## 7. MATRIZ DE RISCO — METODOLOGIA TCU P×I")
    add("")
    add("Escala P (probabilidade) × I (impacto), 1–9 cada. Faixas: Baixo 1–9 | Médio 10–39 | Alto 40–79 | Extremo 80–81.")
    add("")
    add("| Fator de risco | P | I | Score | Faixa |")
    add("|---|---:|---:|---:|---|")
    for fator, pp, ii in _fatores_risco(ctx):
        sc = pp * ii
        faixa = "Baixo" if sc <= 9 else "Médio" if sc <= 39 else "Alto" if sc <= 79 else "Extremo"
        add(f"| {fator} | {pp} | {ii} | {sc} | {faixa} |")
    add("")

    # 9. Red flags com fundamento
    add("## 8. RED FLAGS DE COMPLIANCE")
    add("")
    rf = _red_flags(ctx)
    if rf:
        for titulo, desc, fund in rf:
            add(f"### {titulo}")
            add(f"{desc}")
            add(f"**Fundamento:** {fund}")
            add("")
    else:
        add("_Nenhum red flag automático disparado a partir dos dados locais._")
        add("")

    # 9. Análise jurídica e de mérito — o PARECER escrito do JFN
    add("## 9. ANÁLISE JURÍDICA E DE MÉRITO — PARECER PRELIMINAR DO JFN")
    add("")
    add(parecer_fornecedor(ctx))
    add("")

    # 10. Recomendações
    add("## 10. RECOMENDAÇÕES")
    add("")
    add("**Imediato (0–30 dias):**")
    add("- Cruzar as OBs por ano (tabelas da Seção 2) com os empenhos/liquidações correspondentes no SIAFE.")
    add("- Validar a aderência objeto-contratual dos órgãos de maior concentração (Seção 3).")
    add("")
    add("**Curto prazo (30–90 dias):** abrir os processos SEI dos maiores pagamentos; checar aditivos (>25%).")
    add("")
    add("**Estrutural:** monitoramento contínuo via JFN (timers TFE/OB) e atualização trimestral deste relatório.")
    add("")

    # 11. Referências
    add("## 11. REFERÊNCIAS E FONTES")
    add("")
    add("- **Dados primários:** SIAFE-Rio / Transparência Fiscal RJ (OBs e contratos) — `data/compliance.db`.")
    add("- **Perfil/sanções/rede:** Receita Federal, PNCP, CEIS/CNEP/CEPIM (via `relatorio_riscos`).")
    add("- **Normas:** Lei 14.133/2021; Lei 8.666/93; Lei 4.320/64; CF/88 Art. 37; metodologia TCU P×I; ACFE Report to the Nations 2024.")
    add("")
    add(f"_Relatório gerado automaticamente pelo JFN Intelligence Engine em {ctx['data']}. "
        "Não substitui análise jurídica especializada._")
    add("")
    return "\n".join(L)


def _fatores_risco(ctx: dict) -> list[tuple]:
    p = ctx["pagamentos"]
    fatores = []
    top = p.get("hhi", {}).get("top_share", 0) if p["tem_dados"] else 0
    if top >= 60:
        fatores.append(("Concentração de pagamentos em órgão único", 6, 7))
    elif top >= 40:
        fatores.append(("Concentração relevante de pagamentos por órgão", 4, 6))
    else:
        fatores.append(("Dispersão de pagamentos entre órgãos", 2, 4))
    if ctx["risco"] == "ALTO":
        fatores.append(("Sinais de risco corporativo (perfil/rede)", 6, 6))
    elif ctx["risco"] == "MÉDIO":
        fatores.append(("Sinais de risco corporativo (perfil/rede)", 4, 5))
    # crescimento abrupto ano a ano
    if p["tem_dados"] and len(p["anos"]) >= 2:
        a0, a1 = p["anos"][0], p["anos"][-1]
        t0 = p["por_ano"][a0]["total"] or 1
        t1 = p["por_ano"][a1]["total"]
        if t1 > t0 * 3:
            fatores.append((f"Crescimento abrupto de pagamentos ({a0}→{a1})", 5, 6))
    return fatores or [("Risco base", 2, 3)]


def parecer_fornecedor(ctx: dict) -> str:
    """
    PARECER PRELIMINAR do JFN — análise de MÉRITO e JURÍDICA, escrita a partir dos dados reais.
    É interpretativo e honesto: aponta INDÍCIOS a verificar com fundamento legal, sem juízo de
    culpabilidade nem afirmação de irregularidade (princípio da honestidade + presunção de inocência).
    """
    p = ctx["pagamentos"]
    nome = ctx["nome"]
    L: list[str] = []
    add = L.append

    if not p["tem_dados"]:
        return ("Sem Ordens Bancárias na base local para este CNPJ, não é possível emitir parecer de mérito "
                "sobre a execução financeira. Recomenda-se coleta direta no SIAFE/TFE antes de qualquer conclusão.")

    total = p["total_geral"]
    hhi = p["hhi"]
    top_share = hhi.get("top_share", 0)
    org_top = next(iter(p["por_orgao_geral"]), "—")
    # crescimento
    cresc_txt = ""
    if len(p["anos"]) >= 2:
        a0, a1 = p["anos"][0], p["anos"][-1]
        t0 = p["por_ano"][a0]["total"] or 0
        t1 = p["por_ano"][a1]["total"] or 0
        if t0 > 0:
            pct = (t1 - t0) / t0 * 100
            cresc_txt = (f"Os pagamentos evoluíram de R$ {moeda(t0)} ({a0}) para R$ {moeda(t1)} ({a1}), "
                         f"variação de {pct:+.0f}%. ")
    zeros = sum(1 for a in p["anos"] for ln in p["por_ano"][a]["linhas"] if ln["valor"] == 0)

    # 1) Mérito
    add("### Análise de mérito")
    add("")
    add(f"A empresa **{nome}** recebeu **R$ {moeda(total)}** do Estado do Rio de Janeiro no período analisado, "
        f"em **{p['n_geral']} ordens bancárias** distribuídas por **{len(p['por_orgao_geral'])} unidades gestoras**. "
        f"{cresc_txt}"
        f"O valor é **materialmente relevante** e, por si só, recomenda acompanhamento de controle.")
    add("")
    if top_share >= 60:
        add(f"Chama atenção a **concentração de {top_share:.1f}%** dos pagamentos em um único órgão "
            f"(**{org_top}**), com HHI de {hhi.get('indice')} (concentração {hhi.get('nivel').lower()}). "
            "Concentração dessa ordem, para um prestador de serviços, é atípica e merece verificar se decorre "
            "de contratações competitivas e de objeto compatível com a atividade-fim da empresa, ou se há "
            "dependência institucional que favoreça a fornecedora.")
    elif top_share >= 40:
        add(f"Há **concentração relevante** ({top_share:.1f}%) em **{org_top}** (HHI {hhi.get('indice')}), "
            "o que sugere examinar a competitividade dos certames e a pulverização dos contratos.")
    else:
        add(f"Os pagamentos mostram **dispersão razoável** entre órgãos (maior fatia {top_share:.1f}% em {org_top}; "
            f"HHI {hhi.get('indice')}), o que reduz — mas não elimina — o risco de captura institucional.")
    add("")
    if zeros:
        add(f"Registram-se **{zeros} OB(s) de valor zero** (estornos/regularizações). Volume não trivial de "
            "estornos pode indicar retrabalho de liquidação ou ajustes de execução e merece conferência documental.")
        add("")

    # 2) Jurídico
    add("### Avaliação jurídica")
    add("")
    add("Sob o prisma normativo, os pontos acima devem ser cotejados com:")
    add("")
    add("- **CF/88, art. 37, *caput*** — princípios da impessoalidade, moralidade e eficiência na Administração;")
    add("- **Lei 14.133/2021** (nova Lei de Licitações) — dever de **competitividade** e de **publicidade** dos "
        "contratos no PNCP (art. 94); e **Lei 8.666/93** para contratos remanescentes sob sua vigência;")
    add("- **Lei 8.666/93, art. 65, §1º** — limites de aditivos (25%/50%), quando houver contratos aditivados;")
    add("- **Lei 4.320/64 e Decreto 93.872/86** — regularidade do ciclo empenho→liquidação→pagamento "
        "(vedação a pagamento antecipado sem amparo);")
    add("- **ACFE / TCU** — *red flags* de concentração de fornecedor e de pagamentos atípicos.")
    add("")
    if ctx.get("risco") in ("ALTO", "MÉDIO"):
        add(f"O rating de risco corporativo apurado (**{ctx['risco']}**, score {ctx['score']}/100) reforça a "
            "necessidade de diligência sobre quadro societário e eventuais vínculos.")
        add("")

    # 3) Conclusão / grau de atenção
    grau = "ALTO" if top_share >= 60 or ctx.get("risco") == "ALTO" else ("MÉDIO" if top_share >= 40 or zeros else "MODERADO")
    add("### Conclusão e grau de atenção")
    add("")
    add(f"**Grau de atenção recomendado: {grau}.** Os achados configuram **indícios a verificar** — não "
        "conclusão de irregularidade. Recomenda-se: (i) obter a lista oficial de contratos e respectivos "
        "processos SEI dos maiores pagamentos; (ii) confirmar a modalidade licitatória; (iii) checar aderência "
        "entre objeto contratual e atividade-fim; e (iv) cruzar empenho×liquidação×OB para detectar gaps.")
    add("")
    add("> **Ressalva metodológica:** análise baseada em **dados de pagamento (OB)** de fontes públicas; não "
        "examina o mérito documental de cada contrato. Não há, aqui, juízo de culpabilidade — vigora a "
        "presunção de regularidade dos atos administrativos até prova em contrário.")
    return "\n".join(L)


def _red_flags(ctx: dict) -> list[tuple]:
    p = ctx["pagamentos"]
    out = []
    if p["tem_dados"]:
        hhi = p["hhi"]
        if hhi.get("top_share", 0) >= 60:
            org_top = next(iter(p["por_orgao_geral"]))
            out.append((
                "RF-01 — Concentração extrema em um órgão",
                f"{hhi['top_share']}% do valor pago concentrado em **{org_top}**. Para um fornecedor de serviços, "
                "a dispersão esperada seria maior; concentração extrema exige verificação.",
                "Art. 3 Lei 8.666/93 (isonomia); Art. 37 CF/88 (impessoalidade); ACFE — vendor concentration.",
            ))
        # estornos (OBs valor zero)
        zeros = sum(1 for a in p["anos"] for ln in p["por_ano"][a]["linhas"] if ln["valor"] == 0)
        if zeros:
            out.append((
                "RF-02 — Ordens bancárias com valor zero",
                f"{zeros} OB(s) com valor R$ 0,00 (estornos/regularizações). Volume elevado de estornos pode "
                "indicar retrabalho de execução ou ajustes — vale conferir o motivo.",
                "Boa prática de controle interno (CGE-RJ); rastreabilidade da execução (Lei 4.320/64).",
            ))
    return out


# ───────────────────────────── render PDF (fpdf2) ─────────────────────────────

_FONTES_DEJAVU = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _registrar_fonte(pdf) -> tuple[str, bool]:
    """Registra DejaVu (Unicode) se disponível. Retorna (familia, eh_unicode).
    Italico mapeia para o regular (DejaVuSans nao tem oblique no pacote core)."""
    reg, bold = _FONTES_DEJAVU
    if Path(reg).exists() and Path(bold).exists():
        try:
            pdf.add_font("DejaVu", "", reg)
            pdf.add_font("DejaVu", "B", bold)
            pdf.add_font("DejaVu", "I", reg)
            pdf.add_font("DejaVu", "BI", bold)
            return "DejaVu", True
        except Exception:
            pass
    return "Helvetica", False


def render_pdf(ctx: dict, destino: str) -> str:
    """Gera o PDF due-diligence (inclui as tabelas de OBs por ano). Retorna o caminho salvo."""
    from fpdf import FPDF

    p = ctx["pagamentos"]
    cor_risco = {"ALTO": (220, 53, 69), "MÉDIO": (255, 150, 0), "BAIXO": (40, 167, 69)}.get(ctx["risco"], (90, 90, 90))

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    # Fonte Unicode (DejaVu) p/ acentos e travessões; fallback p/ core latin-1.
    pdf._fam, pdf._uni = _registrar_fonte(pdf)
    pdf.add_page()

    def _t(s: str) -> str:
        s = s or ""
        if getattr(pdf, "_uni", False):
            return s  # fonte Unicode: passa direto
        # core latin-1: normaliza símbolos comuns fora do latin-1
        for a, b in (("—", "-"), ("–", "-"), ("₂", "2"), ("’", "'"), ("“", '"'), ("”", '"'), ("•", "-")):
            s = s.replace(a, b)
        return s.encode("latin-1", "replace").decode("latin-1")

    # Capa
    pdf.set_fill_color(20, 30, 50); pdf.set_text_color(255, 255, 255)
    pdf.set_font(pdf._fam, "B", 16)
    pdf.cell(0, 13, _t("RELATÓRIO DE INTELIGÊNCIA DE FORNECEDOR"), fill=True, ln=True, align="C")
    pdf.set_font(pdf._fam, "", 9); pdf.set_fill_color(45, 60, 90)
    pdf.cell(0, 7, _t("Due Diligence de Integridade · Exposição Financeira · Risco & Compliance"), fill=True, ln=True, align="C")
    pdf.cell(0, 7, _t(f"JFN Intelligence Engine  |  {ctx['data']}"), fill=True, ln=True, align="C")
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "B", 14)
    _mc(pdf, 8, _t(ctx["nome"]))
    pdf.set_font(pdf._fam, "", 10)
    pdf.cell(0, 6, _t(f"CNPJ: {ctx['cnpj_fmt']}"), ln=True)
    pdf.ln(2)
    pdf.set_fill_color(*cor_risco)
    pdf.set_text_color(0, 0, 0) if ctx["risco"] == "MÉDIO" else pdf.set_text_color(255, 255, 255)
    pdf.set_font(pdf._fam, "B", 12)
    pdf.cell(70, 9, _t(f"  RISCO: {ctx['risco']}   Score: {ctx['score']}/100"), fill=True, ln=True)
    pdf.set_text_color(0, 0, 0); pdf.ln(3)
    pdf.set_font(pdf._fam, "", 9)
    _mc(pdf, 5, _t(_resumo_executivo(ctx)))
    pdf.ln(2)
    pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(110, 110, 110)
    _mc(pdf, 4, _t(f"Fonte: OBs/contratos = REAL (SIAFE/TFE) · perfil/sanções/rede = {ctx['fonte_enriq']}. "
                            "OB = pagamento (dado definitivo). Empenho ≠ pagamento."))
    pdf.set_text_color(0, 0, 0)

    # Exposição por exercício
    if p["tem_dados"]:
        pdf.ln(4); pdf.set_font(pdf._fam, "B", 12)
        pdf.cell(0, 8, _t("Exposição financeira — pagamentos por exercício"), ln=True)
        _tab_header(pdf, [("Exercício", 40), ("Nº OBs", 30), ("Valor pago (R$)", 80)])
        pdf.set_font(pdf._fam, "", 9)
        for a in p["anos"]:
            b = p["por_ano"][a]
            _tab_row(pdf, [(str(a), 40, "L"), (str(b["n"]), 30, "R"), (moeda(b["total"]), 80, "R")])
        pdf.set_font(pdf._fam, "B", 9)
        _tab_row(pdf, [("Total", 40, "L"), (str(p["n_geral"]), 30, "R"), (moeda(p["total_geral"]), 80, "R")])

    # Tabelas de OBs por ano (requisito)
    if p["tem_dados"]:
        for a in p["anos"]:
            b = p["por_ano"][a]
            pdf.add_page()
            pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
            pdf.cell(0, 9, _t(f"Pagamentos (OBs) — exercício {a}"), ln=True)
            pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 9)
            pdf.cell(0, 6, _t(f"{b['n']} OBs — Total pago: R$ {moeda(b['total'])}"), ln=True)
            pdf.ln(1)
            _tab_header(pdf, [("#", 10), ("Nº OB", 28), ("Data", 24), ("Órgão (UG)", 90), ("Valor (R$)", 36)])
            pdf.set_font(pdf._fam, "", 7)
            for i, ln in enumerate(b["linhas"], 1):
                _tab_row(pdf, [(str(i), 10, "R"), (_t(ln["numero_ob"]), 28, "L"), (_t(ln["data"])[:10], 24, "L"),
                               (_t(ln["orgao"])[:56], 90, "L"), (moeda(ln["valor"]), 36, "R")], h=4.5)
            pdf.set_font(pdf._fam, "B", 8)
            _tab_row(pdf, [("", 10, "L"), ("", 28, "L"), ("", 24, "L"),
                           (f"Total {a}", 90, "R"), (moeda(b["total"]), 36, "R")], h=5)

    # Concentração por órgão
    if p["tem_dados"]:
        pdf.add_page()
        pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
        pdf.cell(0, 9, _t("Concentração por órgão (HHI)"), ln=True)
        pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 9)
        pdf.cell(0, 6, _t(f"HHI {p['hhi'].get('indice')} — concentração {p['hhi'].get('nivel')} "
                          f"(maior órgão = {p['hhi'].get('top_share')}%)"), ln=True); pdf.ln(1)
        _tab_header(pdf, [("Órgão (UG)", 120), ("Valor pago (R$)", 40), ("%", 20)])
        pdf.set_font(pdf._fam, "", 8)
        tot = p["total_geral"] or 1
        for org, val in p["por_orgao_geral"].items():
            _tab_row(pdf, [(_t(org)[:78], 120, "L"), (moeda(val), 40, "R"), (f"{val/tot*100:.1f}", 20, "R")], h=5)

    # Contratos
    c = ctx["contratos"]
    if c["n"]:
        pdf.add_page()
        pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
        pdf.cell(0, 9, _t(f"Carteira de contratos (SIAFE) — {c['n']} contratos / R$ {moeda(c['total'])}"), ln=True)
        pdf.set_text_color(0, 0, 0)
        _tab_header(pdf, [("Nº", 22), ("Objeto", 78), ("Órgão", 38), ("Valor (R$)", 34)])
        pdf.set_font(pdf._fam, "", 7)
        for ln in c["linhas"]:
            _tab_row(pdf, [(_t(ln["numero"])[:14], 22, "L"), (_t(ln["objeto"])[:50], 78, "L"),
                           (_t(ln["orgao"])[:24], 38, "L"), (moeda(ln["valor"]), 34, "R")], h=4.5)

    # Sinais + red flags (texto)
    pdf.add_page()
    pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
    pdf.cell(0, 9, _t("Sinais de risco e red flags"), ln=True)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 9)
    if ctx["enriq"].get("ok"):
        for s in (ctx["enriq"].get("sinais") or [])[:20]:
            _mc(pdf, 5, _t(f"[{s.get('nivel','')}] {s.get('descricao','')} {('- '+s.get('detalhe','')) if s.get('detalhe') else ''}"))
    else:
        _mc(pdf, 5, _t(f"Perfil/sinais corporativos: {ctx['fonte_enriq']} ({ctx['enriq'].get('_motivo','-')})."))
    pdf.ln(2); pdf.set_font(pdf._fam, "B", 10); pdf.cell(0, 6, _t("Red flags:"), ln=True)
    pdf.set_font(pdf._fam, "", 8)
    rf = _red_flags(ctx)
    if rf:
        for titulo, desc, fund in rf:
            pdf.set_font(pdf._fam, "B", 8); _mc(pdf, 4.5, _t(titulo))
            pdf.set_font(pdf._fam, "", 8); _mc(pdf, 4.5, _t(desc))
            pdf.set_font(pdf._fam, "I", 7); _mc(pdf, 4.5, _t("Fundamento: " + fund)); pdf.ln(1)
    else:
        _mc(pdf, 4.5, _t("Nenhum red flag automático a partir dos dados locais."))

    # Parecer jurídico e de mérito (texto corrido) — o diferencial do JFN
    pdf.add_page()
    pdf.set_font(pdf._fam, "B", 14); pdf.set_text_color(20, 30, 50)
    pdf.cell(0, 10, _t("Análise Jurídica e de Mérito — Parecer Preliminar do JFN"), ln=True)
    pdf.set_text_color(0, 0, 0)
    _render_parecer_pdf(pdf, _t, parecer_fornecedor(ctx))

    pdf.ln(3); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(120, 120, 120)
    _mc(pdf, 4, _t("Gerado automaticamente pelo JFN Intelligence Engine. Não substitui análise jurídica especializada."))

    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(destino)
    return destino


def _render_parecer_pdf(pdf, _t, md_text: str):
    """Renderiza o parecer (markdown leve: ###, **negrito**, '- ', '> ') em texto corrido no PDF."""
    import re as _re
    for raw in md_text.split("\n"):
        linha = raw.rstrip()
        if not linha:
            pdf.ln(1.5)
            continue
        if linha.startswith("### "):
            pdf.ln(1); pdf.set_font(pdf._fam, "B", 11); pdf.set_text_color(30, 45, 70)
            _mc(pdf, 6, _t(linha[4:])); pdf.set_text_color(0, 0, 0)
            continue
        bullet = linha.startswith("- ")
        quote = linha.startswith("> ")
        txt = linha[2:] if (bullet or quote) else linha
        txt = _re.sub(r"\*\*(.+?)\*\*", r"\1", txt)  # remove negrito md (core font sem bold inline)
        if quote:
            pdf.set_font(pdf._fam, "I", 8.5); pdf.set_text_color(90, 90, 90)
            _mc(pdf, 4.6, _t(txt)); pdf.set_text_color(0, 0, 0)
        elif bullet:
            pdf.set_font(pdf._fam, "", 9)
            _mc(pdf, 4.8, _t("•  " + txt))
        else:
            pdf.set_font(pdf._fam, "", 9)
            _mc(pdf, 4.8, _t(txt))


def _mc(pdf, h: float, txt: str, **kw):
    """multi_cell robusto: reseta X para a margem e usa a largura efetiva da página (evita o
    erro 'Not enough horizontal space' quando o cursor ficou deslocado por uma tabela larga)."""
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pdf.epw, h, txt, **kw)


def _tab_header(pdf, cols: list[tuple]):
    pdf.set_fill_color(60, 70, 90); pdf.set_text_color(255, 255, 255); pdf.set_font(pdf._fam, "B", 8)
    for txt, w in cols:
        pdf.cell(w, 6, " " + txt, fill=True, border=1)
    pdf.ln(); pdf.set_text_color(0, 0, 0)


def _tab_row(pdf, cells: list[tuple], h: float = 5.5):
    fill = getattr(pdf, "_zebra", False)
    pdf.set_fill_color(244, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)
    pdf._zebra = not fill
    for txt, w, align in cells:
        pdf.cell(w, h, " " + str(txt), border=1, align=align, fill=True)
    pdf.ln()


# ───────────────────────────── CLI ─────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Uso: python -m compliance_agent.reporting.inteligencia <CNPJ|nome da empresa> [ano1 ano2 ...]")
        sys.exit(1)
    anos_cli = [int(a) for a in args if a.isdigit() and len(a) == 4]
    termo_cli = " ".join(a for a in args if not (a.isdigit() and len(a) == 4)).strip()
    res = gerar(empresa=termo_cli, anos=anos_cli or None)
    print(json.dumps({k: v for k, v in res.items() if k != "resumo"}, ensure_ascii=False, indent=2))
    print("\nRESUMO:", res.get("resumo", ""))
