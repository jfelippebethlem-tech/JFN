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


def cabecalho_frescor() -> str:
    """Cabeçalho de FRESCOR/COBERTURA dos dados de OB (honestidade: afirmar dentro da cobertura). Sem LLM —
    só um COUNT na base. Vazio se a base não estiver acessível. Reusado pelos relatórios de fornecedor/órgão."""
    try:
        import sqlite3
        con = sqlite3.connect(str(_DB))
        try:
            tot = con.execute("SELECT COUNT(*) FROM ordens_bancarias").fetchone()[0] or 0
            cnpj = con.execute("SELECT COUNT(*) FROM ordens_bancarias WHERE length(favorecido_cpf)=14").fetchone()[0] or 0
            ult = con.execute("SELECT MAX(data_pagamento) FROM ordens_bancarias").fetchone()[0]
        finally:
            con.close()
        if not tot:
            return ""
        pct = round(100 * cnpj / tot)
        return (f"> _Cobertura da base: {tot:,} OBs · {pct}% com CNPJ (PJ) · OB mais recente: {ult or '—'}. "
                f"OB = pagamento definitivo (SIAFE/TFE-RJ); afirmações limitadas a esta cobertura._").replace(",", ".")
    except Exception:
        return ""

# retenção: relatórios são REGENERÁVEIS sob demanda (cada /relatorio gera de novo), então não precisam ficar
# acumulando no disco. Mantemos só os recentes (JFN_REPORTS_RETENCAO_DIAS, default 7).
_RETENCAO_DIAS = int(os.environ.get("JFN_REPORTS_RETENCAO_DIAS", "7"))


def _prune_reports():
    """Apaga relatórios gerados (inteligencia*/risco* .md/.pdf/.xlsx) mais antigos que a retenção."""
    try:
        import time as _t
        corte = _t.time() - _RETENCAO_DIAS * 86400
        import itertools
        for f in itertools.chain(_REPORTS.glob("inteligencia*"), _REPORTS.glob("parecer_lex*")):
            try:
                if f.is_file() and f.stat().st_mtime < corte:
                    f.unlink()
            except Exception:
                pass
    except Exception:
        pass

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

    # colapsa estabelecimentos da MESMA raiz (8 díg.) num candidato único — matriz+filiais = uma só PJ
    # (CC arts. 44/985/1.142; STJ REsp 1.286.122). Evita o Yoda "duplicar" a empresa e consolida o total do grupo.
    grupos: "OrderedDict[str, dict]" = OrderedDict()
    for c in cands.values():
        raiz = so_digitos(c["cnpj"])[:8]
        g = grupos.setdefault(raiz, {"membros": [], "total_pago": 0.0, "n_obs": 0})
        g["membros"].append(c)
        g["total_pago"] += c["total_pago"]
        g["n_obs"] += c["n_obs"]
    colapsados = []
    for raiz, g in grupos.items():
        membros = g["membros"]
        # representante: a matriz (0001) se houver, senão o estabelecimento de maior valor pago
        matriz = next((m for m in membros if so_digitos(m["cnpj"])[8:12] == "0001"), None)
        rep = matriz or max(membros, key=lambda m: (m["total_pago"], m["n_obs"]))
        nome = rep["nome"] or ""
        if len(membros) > 1:
            if matriz:
                n_fil = len(membros) - 1
                nome = f"{nome} (matriz + {n_fil} {'filiais' if n_fil > 1 else 'filial'})"
            else:
                nome = f"{nome} ({len(membros)} estabelecimentos — filiais)"
        colapsados.append({"cnpj": rep["cnpj"], "nome": nome, "fonte": rep["fonte"],
                           "total_pago": round(g["total_pago"], 2), "n_obs": g["n_obs"],
                           "raiz": raiz, "n_estabelecimentos": len(membros)})
    ordenados = sorted(colapsados, key=lambda c: (c["total_pago"], c["n_obs"]), reverse=True)
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
           "por_ano": OrderedDict(), "por_orgao_geral": {}, "hhi": {},
           "raiz": so_digitos(cnpj)[:8], "por_estabelecimento": [], "n_estabelecimentos": 0}
    if not _DB.exists():
        return out
    cnpj = so_digitos(cnpj)
    raiz = cnpj[:8]  # consolidar matriz+filiais = uma só PJ (CC 44/985/1.142; STJ REsp 1.286.122)
    con = sqlite3.connect(_DB)
    con.row_factory = sqlite3.Row
    try:
        # LIKE raiz% casa todos os estabelecimentos (matriz 0001 + filiais 0002+) da mesma empresa
        q = ("SELECT numero_ob, data_pagamento, data_emissao, ug_codigo, ug_nome, valor, exercicio, "
             "favorecido_cpf, favorecido_nome FROM ordens_bancarias WHERE favorecido_cpf LIKE ?")
        params: list = [f"{raiz}%"]
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
    # pivot Órgão × Mês × Ano-exercício: (orgao, ano) -> {mes(1..12): total, 0: sem-data}
    orgao_mes_ano: dict = defaultdict(lambda: defaultdict(float))
    # quebra por estabelecimento (matriz/filial) — transparência da consolidação por raiz
    por_estab: dict = {}
    for r in rows:
        ano = int(r["exercicio"] or 0)
        bloco = por_ano.setdefault(ano, {"n": 0, "total": 0.0, "linhas": [], "por_orgao": defaultdict(float)})
        valor = float(r["valor"] or 0.0)
        est_cnpj = so_digitos(r["favorecido_cpf"])
        est = por_estab.setdefault(est_cnpj, {"cnpj": est_cnpj, "nome": r["favorecido_nome"] or "—",
                                              "n": 0, "total": 0.0,
                                              "tipo": "matriz" if est_cnpj[8:12] == "0001" else f"filial {est_cnpj[8:12]}"})
        est["n"] += 1
        est["total"] += valor
        # rótulo canônico da unidade gestora (corrige o nome do órgão superior nas OBs)
        orgao = ugs.rotulo(r["ug_codigo"], r["ug_nome"] or "—")
        data = (r["data_pagamento"] or r["data_emissao"] or "—")
        # mês do pagamento (ISO YYYY-MM-DD); 0 quando a data não vem
        mes = 0
        if isinstance(data, str) and len(data) >= 7 and data[4:5] == "-":
            try:
                mes = int(data[5:7])
                mes = mes if 1 <= mes <= 12 else 0
            except ValueError:
                mes = 0
        bloco["n"] += 1
        bloco["total"] += valor
        bloco["por_orgao"][orgao] += valor
        bloco["linhas"].append({"numero_ob": r["numero_ob"] or "—", "data": data, "orgao": orgao, "valor": valor})
        orgao_geral[orgao] += valor
        orgao_mes_ano[(orgao, ano)][mes] += valor

    for ano, b in por_ano.items():
        b["por_orgao"] = dict(sorted(b["por_orgao"].items(), key=lambda kv: kv[1], reverse=True))
    out["por_ano"] = por_ano
    # consolida o pivot mensal: lista ordenada por (órgão, ano)
    matriz_mes: list[dict] = []
    for (orgao, ano), meses in orgao_mes_ano.items():
        matriz_mes.append({"orgao": orgao, "ano": ano,
                           "meses": {m: round(v, 2) for m, v in meses.items()},
                           "total": round(sum(meses.values()), 2)})
    matriz_mes.sort(key=lambda x: (x["orgao"], x["ano"]))
    out["por_orgao_mes_ano"] = matriz_mes
    # estabelecimentos (matriz+filiais) consolidados nesta empresa (raiz)
    estabs = sorted(por_estab.values(), key=lambda e: e["total"], reverse=True)
    for e in estabs:
        e["total"] = round(e["total"], 2)
    out["raiz"] = raiz
    out["por_estabelecimento"] = estabs
    out["n_estabelecimentos"] = len(estabs)
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


def _crescimento(pagamentos: dict) -> float:
    """Razão pico/base entre exercícios COMPLETOS com dado (>0). 1.0 se não dá p/ medir.
    Mede salto de faturamento atípico (capacidade operacional / aditivos a verificar)."""
    anos = pagamentos.get("anos") or []
    vals = [pagamentos["por_ano"][a]["total"] for a in anos if pagamentos["por_ano"][a]["total"] > 0]
    if len(vals) < 2:
        return 1.0
    base = min(vals)
    return (max(vals) / base) if base > 0 else 1.0


def _recalibrar_risco(pagamentos: dict, rede: list, contratado_tcerj: float,
                      score_ext: int, risco_ext: str) -> dict:
    """Risco JFN = MAIOR entre o score externo e o score interno por sinais REAIS do relatório.
    Corrige o caso em que o enriquecedor externo devolve 0 mas há indícios (conflito, pago≫contratado,
    crescimento atípico, concentração, magnitude). Indício a verificar — nunca acusação."""
    total = float(pagamentos.get("total_geral") or 0)
    top_share = float((pagamentos.get("hhi") or {}).get("top_share") or 0)
    cresc = _crescimento(pagamentos)
    sinais: list[str] = []
    s = 0
    if rede:
        s += 20; sinais.append("conflito doador↔contrato (sócio/empresa doou e é fornecedor)")
    if contratado_tcerj and total > contratado_tcerj * 1.5:
        s += 25; sinais.append(f"pago (R$ {moeda(total)}) ≫ contratado registrado (R$ {moeda(contratado_tcerj)}) — {total/contratado_tcerj:.1f}×")
    elif contratado_tcerj and total > contratado_tcerj * 1.2:
        s += 12; sinais.append(f"pago acima do contratado registrado ({total/contratado_tcerj:.1f}×)")
    if cresc >= 4:
        s += 15; sinais.append(f"crescimento de faturamento atípico (pico/base = {cresc:.1f}×)")
    elif cresc >= 2.5:
        s += 8; sinais.append(f"crescimento de faturamento relevante ({cresc:.1f}×)")
    if top_share >= 60:
        s += 25; sinais.append(f"concentração ≥60% num órgão ({top_share:.0f}%)")
    elif top_share >= 40:
        s += 12; sinais.append(f"concentração relevante no maior órgão ({top_share:.0f}%)")
    if total >= 100e6:
        s += 10; sinais.append(f"exposição muito alta ao erário (R$ {moeda(total)})")
    elif total >= 50e6:
        s += 5; sinais.append(f"exposição alta (R$ {moeda(total)})")
    interno = min(100, s)
    final = max(int(score_ext or 0), interno)
    if final >= 70:
        risco = "ALTO"
    elif final >= 35:
        risco = "MÉDIO"
    elif final >= 15:
        risco = "ATENÇÃO"
    else:
        risco = "BAIXO"
    return {"score": final, "risco": risco, "score_externo": int(score_ext or 0),
            "score_interno": interno, "sinais": sinais}


def consultar_contratos(cnpj: str) -> dict:
    """Contratos oficiais (compliance.db). Retorna {n, total, linhas[...]}."""
    out = {"n": 0, "total": 0.0, "linhas": []}
    if not _DB.exists():
        return out
    cnpj = so_digitos(cnpj)
    raiz = cnpj[:8]  # contratos de TODOS os estabelecimentos da raiz (matriz+filiais = uma PJ)
    con = sqlite3.connect(_DB)
    con.row_factory = sqlite3.Row
    try:
        emps = con.execute("SELECT id FROM empresas WHERE cnpj LIKE ?", (f"{raiz}%",)).fetchall()
        if not emps:
            return out
        ids = [e["id"] for e in emps]
        rows = con.execute(
            "SELECT numero, objeto, orgao_contrat, valor_total, data_assinatura, status "
            "FROM contratos WHERE empresa_id IN (%s) ORDER BY valor_total DESC" % ",".join("?" * len(ids)),
            ids,
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
                 anos: Optional[list[int]] = None, salvar: bool = True, so_resolver: bool = False) -> dict:
    """Monta o relatório de inteligência. Retorna dict (ver docstring do módulo).
    so_resolver=True: só RESOLVE (rápido) e devolve {ok,_resolvido,empresa,cnpj} ou {ambiguo}/{erro}, SEM gerar
    — o endpoint usa p/ tratar a ambiguidade SÍNCRONA (o Yoda roteia a resposta) antes de gerar em background."""
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
    if so_resolver:  # resolveu sem ambiguidade → o endpoint segue p/ geração em background
        return {"ok": True, "_resolvido": cnpj_d, "cnpj": cnpj_d, "empresa": escolhido.get("nome") or termo}

    pagamentos = consultar_pagamentos(cnpj_d, anos)
    contratos = consultar_contratos(cnpj_d)
    cardinalidade = cardinalidade_contratual(cnpj_d)  # OB ≠ contrato ≠ processo (cadeia da despesa, honesto)

    # 4 chamadas INDEPENDENTES em PARALELO (wall-time: soma → máximo). Cada uma é best-effort e não
    # derruba o relatório: enriquecimento (APIs) · cruzamento sócio×OB×SEI×endereço · conflito TSE (DB) ·
    # contratos TCE-RJ (rede). conflito calculado 1× aqui e reusado no render (evita 2ª query).
    async def _cruz():
        try:
            from compliance_agent.cruzamento import cruzar_async
            return await asyncio.wait_for(cruzar_async(cnpj_d), timeout=25)
        except Exception as exc:  # noqa: BLE001
            return {"_erro": str(exc)[:140]}

    async def _conflito_async():
        try:
            from compliance_agent.lex_conflito import conflito as _c
            return (await asyncio.to_thread(_c, cnpj=cnpj_d, limite=30)).get("rede", [])
        except Exception:  # noqa: BLE001
            return []

    async def _tcerj_async():
        try:
            from compliance_agent.collectors.tcerj_aberto import contratos_de_fornecedor
            return await asyncio.wait_for(asyncio.to_thread(contratos_de_fornecedor, cnpj_d, 100), timeout=25)
        except Exception:  # noqa: BLE001
            return []

    enriq, cruz, rede, tcerj_itens = await asyncio.gather(
        _enriquecer(cnpj_d), _cruz(), _conflito_async(), _tcerj_async())
    contratado_tcerj = sum((i.get("valor_contrato") or 0) for i in (tcerj_itens or []) if i.get("_tipo") == "contrato")

    nome = (enriq.get("empresa") or resolv["nome"] or "").strip() or fmt_cnpj(cnpj_d)

    # RISCO recalibrado (externo + sinais internos reais) — corrige "BAIXO 0" com indícios
    cal = _recalibrar_risco(pagamentos, rede, contratado_tcerj, enriq.get("score", 0), enriq.get("risco", "—"))
    risco, score = cal["risco"], cal["score"]

    fonte_global = "REAL" if pagamentos["tem_dados"] else "SEM_DADOS_OB"
    contexto = {
        "cnpj": cnpj_d, "cnpj_fmt": fmt_cnpj(cnpj_d), "nome": nome,
        "data": date.today().isoformat(), "risco": risco, "score": score,
        "pagamentos": pagamentos, "contratos": contratos, "cardinalidade": cardinalidade, "enriq": enriq,
        "fonte_enriq": enriq.get("_fonte", "INDISPONIVEL"),
        "cruzamento": cruz, "conflito_rede": rede,
        "tcerj_itens": tcerj_itens, "contratado_tcerj": contratado_tcerj,
        "calibragem": cal,
    }

    # OSINT keyless (diários oficiais) + ANÁLISE RACIOCINADA — em thread (não bloqueia o event loop),
    # best-effort: nunca derruba nem atrasa o relatório além do bound. (relatório é assíncrono/push.)
    try:
        contexto["gazetas"] = await asyncio.wait_for(
            asyncio.to_thread(_gazetas_lookup, nome, cnpj_d), timeout=20)
    except Exception:  # noqa: BLE001
        contexto["gazetas"] = {}
    try:
        contexto["raciocinio"] = await asyncio.wait_for(
            asyncio.to_thread(parecer_raciocinado, contexto), timeout=55)
    except Exception:  # noqa: BLE001
        contexto["raciocinio"] = ""

    md = render_md(contexto)
    path_md = path_pdf = path_xlsx = ""
    if salvar:
        _prune_reports()  # poda relatórios antigos (regeneráveis sob demanda) antes de salvar os novos
        _REPORTS.mkdir(parents=True, exist_ok=True)
        base = f"inteligencia_{_slug(nome) or cnpj_d}_{contexto['data']}"
        path_md = str(_REPORTS / f"{base}.md")
        Path(path_md).write_text(md, encoding="utf-8")
        try:
            # Onda 7: PDF classe mundial via HTML→Playwright (sem margem estourada/truncamento,
            # com cadastral+sócios+doações+OSINT). FPDF compacto = fallback.
            path_pdf = await render_pdf_html(contexto, str(_REPORTS / f"{base}.pdf"))
        except Exception as exc_html:  # noqa: BLE001
            try:
                path_pdf = render_pdf(contexto, str(_REPORTS / f"{base}.pdf"))
            except Exception as exc:  # noqa: BLE001
                path_pdf = ""
                contexto["_pdf_erro"] = f"html:{str(exc_html)[:70]} | fpdf:{str(exc)[:70]}"
        try:
            from compliance_agent.reporting import planilha
            path_xlsx = planilha.gerar(contexto, str(_REPORTS / f"{base}.xlsx"), modo="fornecedor")
        except Exception as exc:  # noqa: BLE001
            path_xlsx = ""
            contexto["_xlsx_erro"] = str(exc)[:160]

    # 3º documento: PARECER do agente Lex (avaliação jurídica/tomada de contas)
    path_lex = ""
    grau_lex = None
    if salvar:
        try:
            from compliance_agent import lex
            lexout = lex.gerar(contexto)
            path_lex = lexout.get("path_lex_pdf", "")
            grau_lex = lexout.get("grau")
        except Exception as exc:  # noqa: BLE001
            contexto["_lex_erro"] = str(exc)[:160]

    return {
        "ok": True, "cnpj": cnpj_d, "cnpj_fmt": fmt_cnpj(cnpj_d), "empresa": nome,
        "risco": risco, "score": score,
        "resumo": _resumo_executivo(contexto),
        "path_md": path_md, "path_pdf": path_pdf, "path_xlsx": path_xlsx,
        "path_lex": path_lex, "grau_lex": grau_lex,
        "fonte": fonte_global, "fonte_enriq": contexto["fonte_enriq"],
    }


def gerar(cnpj: Optional[str] = None, empresa: Optional[str] = None,
          anos: Optional[list[int]] = None, salvar: bool = True) -> dict:
    """Wrapper síncrono para CLI/uso fora de loop async."""
    return asyncio.run(montar(cnpj=cnpj, empresa=empresa, anos=anos, salvar=salvar))


# Modelo conceitual da cadeia de despesa (ERRO CONCEITUAL a evitar: OB ≠ contrato). A relação é uma ÁRVORE:
# um PROCESSO SEI (licitação / Registro de Preços-SRP) pode gerar VÁRIOS contratos, VÁRIOS aditivos e MUITAS
# OBs; um CONTRATO gera VÁRIAS OBs (parcelas/medições). OB = pagamento (verdade); nunca contar OB como contrato.
_NOTA_CARDINALIDADE = (
    "**Nota conceitual (cadeia da despesa):** a **OB (Ordem Bancária) é o pagamento** — a verdade financeira, "
    "porém **uma parcela**, não um contrato. Um **contrato** gera **várias OBs** (parcelas/medições/aditivos); "
    "um **processo SEI** (licitação ou **Registro de Preços/SRP**) pode gerar **vários contratos**, **aditivos** "
    "e **muitas OBs**. Portanto **nº de OBs ≠ nº de contratos ≠ nº de processos** — os contadores abaixo são "
    "distintos e honestos quanto à cobertura (a vinculação OB→processo só existe onde o SIAFE/SEI a preencheu)."
)


def cardinalidade_contratual(cnpj: str) -> dict:
    """Relação HONESTA OB × processo SEI × contrato p/ um fornecedor (raiz). NÃO equipara níveis.

    {n_obs, n_obs_com_processo, n_processos, cobertura_processo (0..1), n_contratos, _nota}. OB=pagamento;
    um contrato→várias OBs; um processo/SRP→vários contratos+aditivos. cobertura_processo = fração de OBs com
    processo vinculado (o resto é INDISPONÍVEL, não 'sem processo')."""
    out = {"n_obs": 0, "n_obs_com_processo": 0, "n_processos": 0, "cobertura_processo": 0.0,
           "n_contratos": 0, "_nota": ""}
    if not _DB.exists():
        return out
    raiz = so_digitos(cnpj)[:8]
    con = sqlite3.connect(_DB)
    try:
        row = con.execute(
            "SELECT COUNT(*), "
            "  SUM(CASE WHEN (numero_processo IS NOT NULL AND numero_processo!='') "
            "        OR (numero_sei IS NOT NULL AND numero_sei!='') THEN 1 ELSE 0 END), "
            "  COUNT(DISTINCT CASE WHEN numero_processo!='' THEN numero_processo "
            "                      WHEN numero_sei!='' THEN numero_sei END) "
            "FROM ordens_bancarias WHERE favorecido_cpf LIKE ?", (f"{raiz}%",)).fetchone()
        out["n_obs"] = int(row[0] or 0)
        out["n_obs_com_processo"] = int(row[1] or 0)
        out["n_processos"] = int(row[2] or 0)
        try:
            emps = con.execute("SELECT id FROM empresas WHERE cnpj LIKE ?", (f"{raiz}%",)).fetchall()
            if emps:
                ids = [e[0] for e in emps]
                out["n_contratos"] = int(con.execute(
                    "SELECT COUNT(*) FROM contratos WHERE empresa_id IN (%s)" % ",".join("?" * len(ids)),
                    ids).fetchone()[0] or 0)
        except sqlite3.OperationalError:
            pass
    finally:
        con.close()
    out["cobertura_processo"] = round(out["n_obs_com_processo"] / out["n_obs"], 3) if out["n_obs"] else 0.0
    return out


def _frase_cardinalidade(card: dict) -> str:
    """Uma frase honesta com os 3 contadores distintos (OB/processo/contrato) + cobertura."""
    if not card or not card.get("n_obs"):
        return ""
    n_obs, n_proc, n_contr = card["n_obs"], card["n_processos"], card["n_contratos"]
    cob = card.get("cobertura_processo", 0.0)
    partes = [f"{n_obs} OBs (pagamentos)"]
    if n_proc:
        cob_txt = f", cobertura {cob*100:.0f}%" if cob < 0.99 else ""
        partes.append(f"vinculadas a {n_proc} processo(s) SEI distinto(s){cob_txt}")
    if n_contr:
        partes.append(f"{n_contr} contrato(s) na carteira oficial (SIAFE)")
    return ("**Cardinalidade (OB ≠ contrato):** " + "; ".join(partes) +
            ". Um contrato gera várias OBs; um processo/SRP pode gerar vários contratos e aditivos.")


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
    frase_card = _frase_cardinalidade(ctx.get("cardinalidade") or {})
    if frase_card:
        linhas.append(frase_card)
    elif ctx["contratos"]["n"]:
        linhas.append(f"Carteira de contratos (SIAFE): {ctx['contratos']['n']} contratos, "
                      f"R$ {moeda(ctx['contratos']['total'])}.")
    if ctx["risco"] not in ("—", None):
        linhas.append(f"Rating de risco corporativo: {ctx['risco']} (score {ctx['score']}/100).")
    return " ".join(linhas)


def _render_cruzamento(ctx: dict) -> str:
    """Seção 1-B: cruzamento sócio × OB (SIAFE) × processo SEI × endereço."""
    cz = ctx.get("cruzamento") or {}
    L: list[str] = []
    add = L.append
    add("## 1-B. REDE SOCIETÁRIA — CRUZAMENTO SÓCIO × OB × SEI × ENDEREÇO")
    add("")
    add("> Cruza o **quadro societário** (QSA/Receita) com **as OBs do SIAFE**, os **processos SEI** de origem dos "
        "pagamentos e o **endereço (sede)** das empresas. Empresas que compartilham sócio — e sobretudo as que "
        "compartilham a mesma sede — recebendo recursos do mesmo Estado são indício de grupo econômico/empresas-"
        "irmãs a verificar (art. 337-F CP; art. 11 Lei 8.429/92). **Indício, nunca acusação.**")
    add("")

    if cz.get("_erro"):
        add(f"> ⚠️ Cruzamento indisponível nesta execução ({cz['_erro']}). As demais seções não dependem dele.")
        add("")
        return "\n".join(L)

    osi = cz.get("obs_sei") or {}
    add(f"**Pegada do alvo no SIAFE:** {osi.get('n_obs', 0)} OBs · R$ {moeda(osi.get('total_pago', 0))} pagos · "
        f"{osi.get('n_sei', 0)} processo(s) SEI vinculado(s).")
    if cz.get("cidade"):
        add(f"**Cidade-sede do alvo:** {cz['cidade']}.")
    add("")
    seis = osi.get("sei_processos") or []
    if seis:
        amostra = ", ".join(seis[:12]) + (f" (+{len(seis)-12})" if len(seis) > 12 else "")
        add(f"**Processos SEI do alvo (origem das OBs/contratos):** {amostra}")
        add("")

    # Fornecedores na MESMA sede (independe de sócio em comum) — red flag de fachada/laranja
    coend = cz.get("coendereco") or []
    if coend:
        n_pagos = sum(1 for c in coend if c.get("total_pago", 0) > 0)
        add(f"### 🔴 Fornecedores no MESMO endereço ({len(coend)}; {n_pagos} também recebem OBs)")
        add("")
        add("> Empresas com **sede idêntica** ao alvo — mesmo sem sócio declarado em comum. Compartilhar imóvel "
            "entre fornecedores do Estado é indício de empresa de fachada/laranja ou direcionamento "
            "(art. 337-F CP; art. 11 Lei 8.429/92). **Indício a verificar, não acusação.**")
        add("")
        add("| Empresa (CNPJ) | OBs | Pago (R$) | SEI |")
        add("|---|---:|---:|---:|")
        for c in coend[:25]:
            add(f"| {(c.get('razao') or '—')[:48]} ({fmt_cnpj(c['cnpj'])}) | {c.get('n_obs',0)} | "
                f"{moeda(c.get('total_pago',0))} | {c.get('n_sei',0)} |")
        add("")

    if not cz.get("tem_rede"):
        msg = cz.get("_nota") or "Sem rede societária ingerida para este CNPJ."
        if not cz.get("socios"):  # QSA ainda não ingerido → ofereça o comando
            msg += (" Para habilitar o cruzamento por sócio: "
                    "`python -m compliance_agent.rede_societaria --ingerir " + (cz.get("cnpj") or "") + "`.")
        add(f"> {msg}")
        add("")
        return "\n".join(L)

    socios = cz.get("socios") or []
    if socios:
        add(f"**Sócios do alvo (QSA):** {', '.join(socios[:15])}"
            + (f" (+{len(socios)-15})" if len(socios) > 15 else "") + ".")
        add("")

    rel = cz.get("relacionados") or []
    add(f"**Empresas com sócio em comum ({len(rel)}):** ordenadas por sede compartilhada e valor pago.")
    add("")
    add("| Empresa (CNPJ) | Sócio(s) em comum | Cidade-sede | OBs | Pago (R$) | SEI | Mesma sede? |")
    add("|---|---|---|---:|---:|---:|:---:|")
    for r in rel[:25]:
        razao = (r.get("razao") or "—")[:38]
        comuns = (r.get("socios_comuns") or "—")
        comuns = (comuns[:40] + "…") if len(comuns) > 40 else comuns
        cidade = r.get("cidade") or "—"
        if r.get("mesmo_endereco"):
            flag = "🔴 SIM"
        elif r.get("mesma_cidade"):
            flag = "🟡 cidade"
        else:
            flag = "—"
        add(f"| {razao} ({fmt_cnpj(r['cnpj'])}) | {comuns} | {cidade} | {r.get('n_obs',0)} | "
            f"{moeda(r.get('total_pago',0))} | {r.get('n_sei',0)} | {flag} |")
    add("")

    for ind in (cz.get("indicios") or []):
        add(f"> 🟡 **Indício:** {ind}")
        add("")
    return "\n".join(L)


# ───────────────────────────── render Markdown (11 seções) ─────────────────────────────

def _realidade_sede_texto(cnpj: str) -> str:
    """Veredito (texto puro) de realidade da sede do fornecedor (tabela `endereco_verificacao`) — responde
    'a empresa é real?'. Honesto: AFASTADO = sede real/edificada; INDÍCIO = possível baldio/precário (a
    verificar); INDISPONÍVEL/ausente = sem conclusão (cobertura cartográfica incompleta; ≠ inexistência)."""
    cnpj = so_digitos(cnpj or "")
    if not cnpj or not _DB.exists():
        return ""
    try:
        con = sqlite3.connect(str(_DB))
        try:
            row = con.execute("SELECT status,nivel,evidencia FROM endereco_verificacao WHERE cnpj=?",
                              (cnpj,)).fetchone()
        except sqlite3.OperationalError:
            return ""
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return ""
    if not row:
        return "ainda não verificada (sweep de endereços em andamento) — INDISPONÍVEL não é prova de inexistência."
    st, nivel, evid = (row[0] or "").upper(), row[1] or "—", (row[2] or "")[:160]
    if st == "AFASTADO":
        return f"endereço real/edificado — afastada a hipótese de fachada. {evid}".rstrip()
    if st == "INDICIO":
        return (f"🟡 indício ({nivel}) de endereço não edificado/precário — conferir no mapa/imagem/in loco "
                f"antes de concluir. {evid}").rstrip()
    return ("sem conclusão pela base cartográfica aberta (cobertura incompleta) — "
            "INDISPONÍVEL ≠ inexistência (Street View/in loco conclui).")


def _realidade_sede(cnpj: str) -> str:
    """Versão Markdown (bullet) do veredito de realidade da sede."""
    t = _realidade_sede_texto(cnpj)
    return f"- **Realidade da sede:** {t}" if t else ""


def _beneficios_socios(cnpj: str) -> dict:
    """Cruzamento inteligente: benefícios sociais (laranja) dos sócios/admin deste fornecedor (degrada honesto)."""
    try:
        from compliance_agent.reporting import beneficios_view as bv
        return bv.por_fornecedor(so_digitos(cnpj))
    except Exception:  # noqa: BLE001
        return {}


def _render_beneficios_socios(ctx: dict) -> str:
    """Seção 1-C — benefícios de subsistência dos sócios/administradores deste fornecedor (indício de laranja).
    Cruzamento INTELIGENTE: dado completo + leitura raciocinada + conclusão honesta (indício, nunca acusação)."""
    from compliance_agent.reporting import beneficios_view as bv
    b = ctx.get("beneficios_socios")
    if b is None:
        b = _beneficios_socios(ctx.get("cnpj", ""))
    L: list[str] = []
    add = L.append
    add("## 1-C. BENEFÍCIOS SOCIAIS DOS SÓCIOS/ADMINISTRADORES (INDÍCIO DE LARANJA)")
    add("")
    add("> Cruza o **CPF dos sócios/administradores** do QSA com os **benefícios de subsistência** por CPF "
        "(Bolsa Família, BPC, Auxílio Emergencial, PETI, Garantia-Safra, Seguro-Defeso — Portal da "
        "Transparência/CGU). Ser **dono/gestor** de empresa que recebe recursos públicos **e** receber benefício "
        "de subsistência é **indício clássico de testa-de-ferro (laranja)** — interposição de pessoas (art. 337-F "
        "CP; art. 11 Lei 8.429/92). CPF mascarado (LGPD); resolvido por fontes oficiais (favorecidos PF + TSE). "
        "**INDISPONÍVEL ≠ ausência de benefício.**")
    add("")
    if not b or not b.get("total_qsa"):
        add("_Sem sócios/administradores com CPF mascarado no QSA deste fornecedor (ou QSA público não ingerido) "
            "— **INDISPONÍVEL** (não equivale a ausência de benefício)._")
        return "\n".join(L)
    add(bv.leitura(b, escopo="deste fornecedor"))
    add("")
    add(f"- Sócios/administradores no QSA (mascarados): **{b['total_qsa']}** · já varridos: **{b['n_varridos']}** · "
        f"CPF resolvido: **{b['n_resolvidos']}** · verificados: **{b['n_verificados']}** ({b['cobertura']}%) · "
        f"**INDISPONÍVEL:** {b['n_indisponivel']}")
    itens = b.get("itens") or []
    if itens:
        add("")
        add("| Sócio/Administrador | Papel | Benefício | Fonte do CPF |")
        add("|---|---|---|---|")
        _f = {"favorecidos_pf": "favorecidos PF", "tse_doadores": "doadores TSE"}
        for it in itens:
            tipos = ", ".join(it.get("tipos") or []) or "(tipo não detalhado)"
            add(f"| {it.get('nome', '')} | {it.get('papel', '')} | {tipos} | "
                f"{_f.get(it.get('fonte', ''), it.get('fonte', '') or '—')} |")
        add("")
        add("> 🟡 **Indício a confirmar:** sócio/gestor que recebe benefício de subsistência sugere **interposição "
            "de pessoas (laranja)** — confirmar no contrato social, na procuração e no processo SEI. **Indício, não "
            "prova.** CPF de uso interno (LGPD).")
    add("")
    return "\n".join(L)


def _render_doacoes_tse(ctx: dict) -> str:
    """Seção 1-D — doações eleitorais (TSE) × contratos: conflito doador↔contrato. Cruzamento inteligente
    (paridade com o PDF): dado completo (cadeia doador→fornecedor→candidato→UG→SEI) + leitura + conclusão."""
    rede = ctx.get("conflito_rede")
    if rede is None:
        try:
            from compliance_agent.lex_conflito import conflito
            rede = conflito(cnpj=so_digitos(ctx.get("cnpj", "")), limite=30).get("rede", [])
        except Exception:  # noqa: BLE001
            rede = []
    if isinstance(rede, dict):
        rede = rede.get("rede", [])
    L: list[str] = []
    add = L.append
    add("## 1-D. DOAÇÕES ELEITORAIS — CONFLITO DOADOR ↔ CONTRATO (TSE)")
    add("")
    add("> Cruza as **doações eleitorais** (TSE) da empresa **e de seus sócios** com os contratos/pagamentos do "
        "Estado, fechando a cadeia **doador → fornecedor → candidato → UG pagadora → processo SEI**. Doar a "
        "campanha e contratar com o poder público é **indício de relação política / conflito de interesse** a "
        "verificar (Lei 9.504/97; Lei 14.133 art. 14) — presunção de legitimidade, **nunca acusação**.")
    add("")
    if not rede:
        add("_Nenhuma doação eleitoral (TSE) localizada para a empresa ou seus sócios na base — **INDISPONÍVEL / "
            "sem registro** (não equivale a inexistência de doação fora do período/base ingerida)._")
        add("")
        return "\n".join(L)
    add(f"**{len(rede)}** vínculo(s) doação↔contrato localizado(s) — o doador pode ser a empresa OU um sócio (coluna *Via*):")
    add("")
    add("| Doador | Via | Candidato | Partido | Ano | Valor doado (R$) | Órgão (UG) pagador | Processos SEI |")
    add("|---|---|---|---|---:|---:|---|---|")
    for r in rede[:20]:
        ugs = r.get("ugs") or []
        ug_cell = ("; ".join(f"{u.get('nome')} (R$ {moeda(u.get('total'))})" for u in ugs[:2])
                   + (f" (+{len(ugs) - 2} UG)" if len(ugs) > 2 else "")) if ugs else "—"
        seis = r.get("seis") or []
        sei_cell = (", ".join(str(s) for s in seis[:5]) + (f" (+{len(seis) - 5})" if len(seis) > 5 else "")) if seis else "—"
        add(f"| {r.get('doador', '')} | {r.get('via', '')} | {r.get('candidato', '')} | {r.get('partido', '')} "
            f"| {r.get('ano', '')} | {moeda(r.get('valor_doacao'))} | {ug_cell} | {sei_cell} |")
    add("")
    add("> 🟡 **Indício a verificar:** doação eleitoral de fornecedor (ou de seu sócio) a candidato, combinada com "
        "recebimento de recursos públicos no Estado, é indício de **relação política / conflito de interesse** — "
        "confirmar a cadeia (doação→contrato→UG→SEI) e a regularidade do certame. **Indício, não prova.**")
    add("")
    return "\n".join(L)


def _rodizio_fornecedor(cnpj: str, max_ugs: int = 3) -> dict:
    """A4 — o fornecedor é 'campeão' de algum anel de rodízio (bid rotation/cartel) nas UGs que mais o pagam?
    Bounded (top `max_ugs` por valor); reusa `rodizio_temporal.rodizio_orgao` (DuckDB). Degrada honesto."""
    cnpj = so_digitos(cnpj)
    out = {"ok": False, "ugs_avaliadas": 0, "aneis": []}
    if len(cnpj) != 14:
        return out
    try:
        con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
        try:
            ugs = [str(r[0]) for r in con.execute(
                "SELECT ug_codigo FROM ordens_bancarias WHERE favorecido_cpf=? AND ug_codigo IS NOT NULL "
                "GROUP BY ug_codigo ORDER BY SUM(valor) DESC LIMIT ?", (cnpj, max_ugs)).fetchall()]
        finally:
            con.close()
        if not ugs:
            return out
        from compliance_agent import rodizio_temporal as rt
        for ug in ugs:
            try:
                r = rt.rodizio_orgao(ug)
            except Exception:  # noqa: BLE001
                continue
            out["ugs_avaliadas"] += 1
            if r.get("indicio"):
                camp = next((c for c in r.get("campeoes", []) if so_digitos(c.get("cnpj", "")) == cnpj), None)
                if camp:
                    out["aneis"].append({"ug": ug, "score": r.get("score"), "n_campeoes": r.get("n_campeoes"),
                                         "share_ring": r.get("share_ring"), "n_vitorias": camp.get("n_vitorias"),
                                         "anos": camp.get("anos", [])})
        out["ok"] = out["ugs_avaliadas"] > 0
        return out
    except Exception as exc:  # noqa: BLE001
        out["_nota"] = str(exc)[:160]
        return out


def _render_rodizio_fornecedor(ctx: dict) -> str:
    """Seção 1-E — rodízio de vencedores (bid rotation/cartel) do fornecedor. Dado + leitura + conclusão honesta."""
    rod = ctx.get("rodizio_forn")
    if rod is None:
        rod = _rodizio_fornecedor(ctx.get("cnpj", ""))
    L: list[str] = []
    add = L.append
    add("## 1-E. RODÍZIO DE VENCEDORES / CARTEL (BID ROTATION)")
    add("")
    add("> Verifica se este fornecedor é um dos **'campeões' que se revezam no topo** das UGs que mais o pagam — "
        "padrão de **bid rotation** (rodízio de vencedores), *red flag* de cartel/conluio (OCDE *Guidelines*; Lei "
        "12.529/11 art. 36; Lei 8.666 art. 90). A OB expõe o **vencedor**, não os licitantes — corroborar no "
        "SEI/PNCP. **Indício, não prova.**")
    add("")
    if not rod.get("ok"):
        add("_Sem UGs suficientes para avaliar rodízio, ou avaliação indisponível nesta execução — **INDISPONÍVEL**._")
        add("")
        return "\n".join(L)
    aneis = rod.get("aneis") or []
    if not aneis:
        add(f"Avaliadas as **{rod['ugs_avaliadas']}** UG(s) que mais pagam este fornecedor: **nenhum anel de "
            "rodízio** com este fornecedor como campeão (indício de cartel **afastado** para essas UGs; as demais "
            "UGs do fornecedor não foram avaliadas — INDISPONÍVEL).")
        add("")
        return "\n".join(L)
    add(f"🟡 **Indício:** este fornecedor figura como **campeão de rodízio** em **{len(aneis)}** UG(s):")
    add("")
    add("| UG | Score do anel | Nº campeões | Vitórias do fornecedor | Anos no topo | Dominância do anel |")
    add("|---|---:|---:|---:|---|---:|")
    for a in aneis:
        anos = ", ".join(str(y) for y in (a.get("anos") or []))
        add(f"| {a['ug']} | {a.get('score')} | {a.get('n_campeoes')} | {a.get('n_vitorias')}× | {anos} "
            f"| {a.get('share_ring')} |")
    add("")
    add("> 🟡 **Indício a corroborar:** revezamento sistemático no topo sugere **bid rotation / cartel** — "
        "confirmar a lista de licitantes (SEI/PNCP) e sócios em comum entre os campeões. **Indício, não prova.**")
    add("")
    return "\n".join(L)


def _num_brl(v):
    """Converte capital social (número ou string '1.234,56') p/ float; None se não der."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(".", "").replace(",", "."))
    except Exception:  # noqa: BLE001
        return None


def _capital_recebido_md(emp: dict | None, pagamentos: dict) -> str:
    """A8 — leitura inteligente capital social × recebido (subcapitalização típica de fachada). Indício honesto.
    Limiar espelha o H-CAPITAL do motor DD: recebido ≥ 50× capital e > R$ 500 mil = indício (ALTO se ≥ 200×)."""
    if not emp:
        return ""
    cap = _num_brl(emp.get("capital_social"))
    total = (pagamentos or {}).get("total_geral") or 0
    if cap is None or total <= 0:
        return ""
    if cap <= 0:
        return ("- **Capital × recebido:** capital social declarado **nulo/não informado** frente a "
                f"R$ {moeda(total)} recebidos do Estado — **atenção** (capital irrisório/ausente é indício de "
                "subcapitalização a verificar; INDISPONÍVEL não equivale a regular).")
    razao = total / cap
    if total >= 50 * cap and total > 500_000:
        nivel = "🔴 ALTO" if razao >= 200 else "🟡 MÉDIO"
        return (f"- **Capital × recebido ({nivel}):** capital social de **R$ {moeda(cap)}** contra "
                f"**R$ {moeda(total)}** recebidos (**{razao:,.0f}× o capital**) — **indício** de subcapitalização "
                "típica de empresa de fachada; verificar a capacidade econômico-financeira (art. 11 Lei 8.429/92; "
                "Lei 14.133/21 art. 69). **Indício, não prova.**")
    return (f"- **Capital × recebido:** capital social de R$ {moeda(cap)} frente a R$ {moeda(total)} recebidos "
            f"({razao:,.1f}× o capital) — proporção **sem indício relevante** de subcapitalização.")


def _render_conflito_pessoal(ctx: dict) -> str:
    """Seção 1-F — sócio/admin (CPF resolvido) na folha do Estado = conflito de pessoal. Dado + leitura + conclusão."""
    from compliance_agent.reporting import conflito_pessoal_view as cp
    agg = ctx.get("conflito_pessoal")
    if agg is None:
        agg = cp.por_fornecedor(so_digitos(ctx.get("cnpj", "")))
    L: list[str] = []
    add = L.append
    add("## 1-F. CONFLITO DE PESSOAL — SÓCIO/ADMINISTRADOR NA FOLHA DO ESTADO")
    add("")
    add("> Cruza os sócios/administradores (com **CPF resolvido**) com a **folha do Estado** (servidores/"
        "terceirizados/bolsistas — `registros_folha`). Ser sócio/gestor de empresa contratada pelo poder público "
        "**e** integrar sua folha é indício de **conflito de interesse / incompatibilidade** (CF art. 37; Lei "
        "8.429/92 art. 11; Lei 14.133/21 art. 9º). O CPF do QSA é resolvido por ponte probabilística (~5% do QSA) "
        "→ cobertura limitada; **INDISPONÍVEL ≠ ausência**. Indício, **nunca acusação**.")
    add("")
    add(cp.leitura(agg))
    itens = agg.get("itens") or []
    if itens:
        add("")
        add("| Sócio/Administrador | Papel (QSA) | Órgão (folha) | Cargo | Vínculo | Competência |")
        add("|---|---|---|---|---|---|")
        for it in itens[:20]:
            add(f"| {it['nome']} | {it['papel']} | {it['orgao']} | {it['cargo']} | {it['vinculo']} | {it['competencia']} |")
        add("")
        add("> 🟡 **Indício a confirmar:** confirmar a identidade (CPF resolvido por ponte) e a natureza do vínculo "
            "(acumulação lícita de cargos? impedimento de contratar? art. 9º Lei 14.133). **Indício, não prova.**")
    add("")
    return "\n".join(L)


def _render_benford(ctx: dict) -> str:
    """Seção 8-B — Lei de Benford sobre os valores de OB (triagem estatística de fracionamento/fabricação)."""
    p = ctx.get("pagamentos") or {}
    L: list[str] = []
    add = L.append
    add("## 8-B. ANÁLISE ESTATÍSTICA DOS VALORES (LEI DE BENFORD)")
    add("")
    add("> A Lei de Benford prevê a frequência do **1º dígito** em populações de valores naturais (pagamentos). "
        "Um desvio relevante (MAD de Nigrini) é **indício** estatístico de fracionamento, valores fabricados ou "
        "direcionamento — **nunca prova**; amostras pequenas (n<50) são pouco confiáveis. Triagem, a confirmar nos documentos.")
    add("")
    if not p.get("tem_dados"):
        add("_Sem Ordens Bancárias na base para este fornecedor — **INDISPONÍVEL**._")
        add("")
        return "\n".join(L)
    try:
        from compliance_agent.analysis.benford import benford
        vals = [ln.get("valor") or 0 for a in p["anos"] for ln in p["por_ano"][a].get("linhas", [])
                if (ln.get("valor") or 0) > 0]
        bf = benford(vals)
    except Exception:  # noqa: BLE001
        add("_Análise de Benford indisponível nesta execução._")
        add("")
        return "\n".join(L)
    d1 = bf.get("primeiro_digito") or {}
    faixa = d1.get("faixa_nigrini", "—")
    conforme = "CONFORM" in faixa.upper() and "NÃO" not in faixa.upper()
    add(f"**1º dígito** (n={d1.get('n', 0)} OBs): **MAD de Nigrini = {d1.get('mad', '—')}** → **{faixa}**.")
    if not bf.get("suficiente"):
        add(f"> ⚠️ Amostra pequena (n={d1.get('n', 0)} < 50) — resultado **pouco confiável**, informativo apenas.")
    add("")
    obs = d1.get("obs") or {}
    esp = d1.get("esp") or {}
    add("| Dígito | Esperado (Benford) | Observado | Δ (pp) |")
    add("|---:|---:|---:|---:|")
    for dig in range(1, 10):
        e = float(esp.get(str(dig), 0) or 0)
        o = float(obs.get(str(dig), 0) or 0)
        add(f"| {dig} | {e * 100:.1f}% | {o * 100:.1f}% | {(o - e) * 100:+.1f} |")
    add("")
    if conforme:
        add("> ✅ **Conforme** — a distribuição dos 1ºs dígitos é compatível com Benford; **sem indício** estatístico "
            "de fracionamento/fabricação de valores (não afasta outras irregularidades).")
    else:
        add("> 🟡 **Não conformidade** — a distribuição se afasta do esperado; **indício** estatístico a verificar "
            "(fracionamento, valores fabricados, direcionamento). Confirmar nos contratos/OBs — Benford é triagem, não prova.")
    add("")
    return "\n".join(L)


def render_md(ctx: dict) -> str:
    p = ctx["pagamentos"]
    L: list[str] = []
    add = L.append

    add("# RELATÓRIO DE INTELIGÊNCIA DE FORNECEDOR")
    add(f"### {ctx['nome']}")
    add("")
    add("*Due Diligence de Integridade · Exposição Financeira · Risco & Compliance*")
    add("")
    add(f"**CNPJ:** {ctx['cnpj_fmt']}  |  **Data:** {ctx['data']}  |  **Analista:** JFN Intelligence Engine")
    add("**Metodologia:** due diligence de integridade (padrão Kroll/Deloitte) · matriz de risco TCU P×I · OB = pagamento (fonte de verdade)")
    add(f"**Classificação de fonte:** OBs/Contratos = **REAL** (SIAFE/TFE) · Perfil/Sanções/Rede = **{ctx['fonte_enriq']}**")
    add("")
    add("---")
    add("")
    _fr = cabecalho_frescor()  # honestidade: cobertura/frescor da base no topo
    if _fr:
        add(_fr)
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
        # Município/UF: o enrich às vezes vem sem esses campos separados; o cruzamento já os
        # extrai do endereço (mesma fonte que alimenta "Cidade-sede" na Seção 1-B) — fallback honesto.
        _endcz = (ctx.get("cruzamento") or {}).get("endereco") or {}
        _mun = emp.get("municipio") or _endcz.get("municipio") or "—"
        _uf = emp.get("uf") or _endcz.get("uf") or "—"
        campos = [
            ("Razão social", emp.get("razao_social")), ("Situação", emp.get("situacao")),
            ("Data de abertura", emp.get("data_abertura")), ("Porte", emp.get("porte")),
            ("Natureza jurídica", emp.get("natureza_juridica")), ("Capital social", f"R$ {moeda(emp.get('capital_social'))}"),
            ("CNAE principal", emp.get("cnae_principal")), ("Município/UF", f"{_mun}/{_uf}"),
            ("Endereço (sede)", emp.get("endereco")),
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
        # endereço da sede via cruzamento (BrasilAPI direto), mesmo sem o enriquecimento completo
        _end = (ctx.get("cruzamento") or {}).get("endereco") or {}
        if _end.get("endereco"):
            add("")
            add(f"- **Endereço (sede):** {_end['endereco']}")
    # realidade da sede (a empresa é real?) — cruza a verificação de endereço do próprio CNPJ
    _rs = _realidade_sede(ctx.get("cnpj", ""))
    if _rs:
        add(_rs)
    # A8 — capital social × recebido (subcapitalização típica de fachada)
    _cr = _capital_recebido_md(emp, p)
    if _cr:
        add(_cr)
    add("")

    # 1-B. Cruzamento sócio × OB (SIAFE) × processo SEI × endereço
    add(_render_cruzamento(ctx))

    # 1-C. Cruzamento de benefícios sociais dos sócios/administradores (laranja/testa-de-ferro)
    add(_render_beneficios_socios(ctx))

    # 1-D. Doações eleitorais (TSE) × contratos — conflito doador↔contrato (paridade com o PDF)
    add(_render_doacoes_tse(ctx))

    # 1-E. Rodízio de vencedores / cartel (bid rotation) — o fornecedor é campeão de algum anel?
    if "rodizio_forn" not in ctx:
        ctx["rodizio_forn"] = _rodizio_fornecedor(ctx.get("cnpj", ""))
    add(_render_rodizio_fornecedor(ctx))

    # 1-F. Conflito de pessoal — sócio/administrador (CPF resolvido) na folha do Estado
    add(_render_conflito_pessoal(ctx))

    # 3. Pagamentos (OBs) por ano — TABELA POR ANO (requisito do Mestre Jorge)
    add("## 2. PAGAMENTOS (ORDENS BANCÁRIAS) POR ANO")
    add("")
    add("> Fonte: SIAFE/TFE-RJ (Ordem Bancária = dado **definitivo de pagamento**). Por exercício, as **maiores "
        "OBs** (materiais); a **lista completa** de cada pagamento está na **planilha XLSX** deste relatório. "
        "OBs de R$ 0,00 são estornos/regularizações (entram na contagem, não somam ao total).")
    add("")
    add(f"> {_NOTA_CARDINALIDADE}")
    card = ctx.get("cardinalidade") or {}
    if card.get("n_obs"):
        add("")
        add(f"> {_frase_cardinalidade(card)}")
    add("")
    if p["tem_dados"]:
        TOP_OB_ANO = 12  # padrão de due diligence: destacar o material; o detalhe completo vai na planilha
        for a in p["anos"]:
            b = p["por_ano"][a]
            add(f"### Exercício {a} — {b['n']} OBs — Total pago: R$ {moeda(b['total'])}")
            add("")
            maiores = sorted(b["linhas"], key=lambda ln: -(ln.get("valor") or 0))[:TOP_OB_ANO]
            add("| # | Nº OB | Data pagamento | Órgão (UG) | Valor (R$) |")
            add("|---:|---|---|---|---:|")
            for i, ln in enumerate(maiores, 1):
                add(f"| {i} | {ln['numero_ob']} | {ln['data']} | {ln['orgao']} | {moeda(ln['valor'])} |")
            add(f"| | | | **Total {a} ({b['n']} OBs)** | **{moeda(b['total'])}** |")
            if b["n"] > len(maiores):
                add("")
                add(f"> _{len(maiores)} maiores de {b['n']} OBs do exercício — lista completa na planilha XLSX._")
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

    # 4-B. Contratos e compras diretas no TCE-RJ (Dados Abertos — independe do SEI/WAF)
    add("## 4-B. CONTRATOS E COMPRAS DIRETAS — TCE-RJ (Dados Abertos)")
    add("")
    try:
        from compliance_agent.collectors.tcerj_aberto import contratos_de_fornecedor
        _itens = contratos_de_fornecedor(ctx["cnpj"], limite=100)
    except Exception:
        _itens = []
    _ctr = [i for i in _itens if i.get("_tipo") == "contrato"]
    _cmp = [i for i in _itens if i.get("_tipo") == "compra_direta"]
    if _ctr or _cmp:
        _soma_ctr = sum(i.get("valor_contrato") or 0 for i in _ctr)
        _soma_cmp = sum(i.get("valor") or 0 for i in _cmp)
        _dispensa = [i for i in _cmp if any(k in ((i.get("afastamento") or "") + " " +
                     (i.get("enquadramento_legal") or "")).lower() for k in ["dispensa", "inexigibil"])]
        add(f"O controle externo (TCE-RJ) registra **{len(_ctr)} contrato(s)** (R$ {moeda(_soma_ctr)}) e "
            f"**{len(_cmp)} compra(s) direta(s)** (R$ {moeda(_soma_cmp)}; {len(_dispensa)} por dispensa/"
            "inexigibilidade). Fonte oficial, independe do SEI.")
        add("")
        # contratado (TCE-RJ) vs pago (OBs) — leitura de execução
        _pago = (ctx.get("pagamentos") or {}).get("total_geral") or 0
        if _soma_ctr and _pago:
            _r = _pago / _soma_ctr * 100
            add(f"> **Contratado vs. pago:** R$ {moeda(_soma_ctr)} contratados (TCE-RJ) × R$ {moeda(_pago)} pagos "
                f"em OBs (SIAFE/TFE) = **{_r:.0f}%** de execução financeira sobre o valor contratado registrado. "
                "(Pago superior ao contratado pode indicar aditivos/contratos não listados — verificar.)")
            add("")
        if _ctr:
            add("**Contratos (maiores por valor):**")
            add("")
            add("| Processo | Ano | Objeto | Critério | Valor (R$) | Unidade |")
            add("|---|---:|---|---|---:|---|")
            for i in _ctr[:10]:
                obj = (i.get("objeto") or "").strip()
                obj = (obj[:55] + "…") if len(obj) > 55 else (obj or "—")
                proc = (i.get("processo") or "").split(",")[0].strip()
                proc = proc + (f" (+{len(i['processo'].split(','))-1})" if "," in (i.get("processo") or "") else "")
                add(f"| {proc} | {i.get('ano_processo','')} | {obj} | {i.get('criterio_julgamento') or '—'} | "
                    f"{moeda(i.get('valor_contrato'))} | {(i.get('unidade') or '')[:28]} |")
            add("")
        if _dispensa:
            add("**Compras diretas (dispensa/inexigibilidade — fundamento legal):**")
            add("")
            add("| Processo | Ano | Objeto | Afastamento | Enquadramento legal | Valor (R$) |")
            add("|---|---:|---|---|---|---:|")
            for i in _dispensa[:10]:
                obj = (i.get("objeto") or "").strip()
                obj = (obj[:40] + "…") if len(obj) > 40 else (obj or "—")
                enq = (i.get("enquadramento_legal") or "").strip()
                enq = (enq[:50] + "…") if len(enq) > 50 else (enq or "—")
                add(f"| {(i.get('processo') or '').split(',')[0].strip()} | {i.get('ano_processo','')} | {obj} | "
                    f"{i.get('afastamento') or '—'} | {enq} | {moeda(i.get('valor'))} |")
            add("")
    else:
        add("_Sem contratos ou compras diretas deste CNPJ na base de Dados Abertos do TCE-RJ "
            "(pode ser contratação municipal/federal ou ainda não publicada)._")
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

    # 8-B. Análise estatística (Lei de Benford) — paridade com o PDF
    add(_render_benford(ctx))

    # 9. Análise jurídica e de mérito — o PARECER escrito do JFN
    add("## 9. ANÁLISE JURÍDICA E DE MÉRITO — PARECER PRELIMINAR DO JFN")
    add("")
    raciocinio = ctx.get("raciocinio")
    if raciocinio:
        add("### Análise raciocinada — cruzamento dos achados (IA sobre os fatos coletados)")
        add("")
        add(raciocinio)
        add("")
        add("> _Síntese gerada por IA **a partir dos fatos coletados** (não inventa dados); indícios para "
            "apuração, não conclusão. O parecer estruturado abaixo permanece como base._")
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


def _gazetas_lookup(nome: str, cnpj: str) -> dict:
    """Diários oficiais municipais (Querido Diário, keyless). Best-effort; INDISPONÍVEL honesto."""
    try:
        from compliance_agent.providers import lookup
        q = f'"{nome}"' if nome and not nome.replace(".", "").replace("/", "").isdigit() else cnpj
        r = lookup("gazettes", querystring=q, size=8)
        return r.dados if r.ok else {"_indisponivel": r.erro or r.estado}
    except Exception as e:  # noqa: BLE001
        return {"_indisponivel": str(e)[:60]}


def _fatos_para_raciocinio(ctx: dict) -> str:
    """Compila os FATOS já coletados (sem inventar) p/ a análise raciocinada conectar."""
    p = ctx["pagamentos"]
    L: list[str] = [f"Fornecedor: {ctx['nome']} (CNPJ {ctx['cnpj_fmt']}). "
                    f"Rating interno de risco: {ctx.get('risco')} (score {ctx.get('score')}/100)."]
    if p.get("tem_dados"):
        hhi = p["hhi"]
        org = next(iter(p["por_orgao_geral"]), "—")
        L.append(f"Pagamentos (OB): R$ {moeda(p['total_geral'])} em {p['n_geral']} ordens bancárias, "
                 f"{len(p['por_orgao_geral'])} unidades gestoras; maior concentração "
                 f"{hhi.get('top_share', 0):.1f}% em '{org}' (HHI {hhi.get('indice')}, nível {hhi.get('nivel')}).")
        zeros = sum(1 for a in p["anos"] for ln in p["por_ano"][a]["linhas"] if ln["valor"] == 0)
        if zeros:
            L.append(f"{zeros} OB(s) de valor zero (estornos/regularizações).")
    else:
        L.append("Sem Ordens Bancárias na base local para este CNPJ.")
    cz = ctx.get("cruzamento") or {}
    if cz.get("coendereco"):
        L.append(f"Cruzamento: {len(cz['coendereco'])} outro(s) fornecedor(es) do Estado no MESMO endereço do alvo.")
    rel = cz.get("relacionados") or []
    if rel:
        me = sum(1 for r in rel if r.get("mesmo_endereco"))
        L.append(f"Cruzamento: {len(rel)} empresa(s) com SÓCIO em comum com o alvo"
                 + (f" ({me} também no mesmo endereço)" if me else "") + ".")
    if (cz.get("obs_sei") or {}).get("n_sei"):
        L.append(f"Processos SEI vinculados ao alvo: {cz['obs_sei']['n_sei']}.")
    cr = ctx.get("conflito_rede") or {}
    n_conf = (cr.get("n") if isinstance(cr, dict) else 0) or len(cr.get("rede") or []) if isinstance(cr, dict) else 0
    if n_conf:
        L.append(f"Conflito doador↔contrato (TSE): {n_conf} vínculo(s) entre doação eleitoral e o alvo/sócios.")
    sanc = (ctx["enriq"].get("dados") or {}).get("sancoes") if ctx.get("enriq", {}).get("ok") else None
    if isinstance(sanc, dict) and sanc.get("verificado"):
        n = sanc.get("n_sancoes", 0)
        L.append(f"Sanções CEIS/CNEP (consulta verificada): {('SIM — ' + str(n) + ' registro(s)') if n else 'nada localizado'}.")
    gz = ctx.get("gazetas") or {}
    if gz.get("total"):
        muns = ", ".join(dict.fromkeys(f"{i['municipio']}/{i['uf']}" for i in (gz.get("itens") or [])[:5] if i.get("municipio")))
        L.append(f"Diários oficiais (Querido Diário): {gz['total']} menção(ões) ao nome em diários municipais; ex.: {muns}.")
    emp_r = (ctx["enriq"].get("dados") or {}).get("empresa") if ctx.get("enriq", {}).get("ok") else None
    if emp_r and p.get("tem_dados"):
        _cap = _num_brl(emp_r.get("capital_social"))
        if _cap and _cap > 0 and p["total_geral"] >= 50 * _cap and p["total_geral"] > 500_000:
            L.append(f"Capital social ({moeda(_cap)}) é {p['total_geral'] / _cap:,.0f}× menor que o recebido "
                     f"({moeda(p['total_geral'])}) — indício de subcapitalização típica de fachada (H-CAPITAL).")
    rodf = ctx.get("rodizio_forn") or {}
    if rodf.get("aneis"):
        _ugs = ", ".join(str(a["ug"]) for a in rodf["aneis"])
        L.append(f"Rodízio de vencedores (bid rotation/cartel): este fornecedor é campeão de anel em "
                 f"{len(rodf['aneis'])} UG(s) ({_ugs}) — indício de conluio/cartel a corroborar (lista de "
                 "licitantes no SEI/PNCP; sócios em comum entre os campeões).")
    bs = ctx.get("beneficios_socios") or _beneficios_socios(ctx.get("cnpj", ""))
    if bs.get("n_verificados"):
        if bs.get("n_com_beneficio"):
            L.append(f"Benefício social de subsistência (laranja): {bs.get('n_pessoas_beneficio', 0)} sócio(s)/"
                     f"administrador(es) verificado(s) recebe(m) benefício (de {bs['n_verificados']} verificados) — "
                     "indício de interposição de pessoas (testa-de-ferro), a confirmar no contrato social/SEI.")
        else:
            L.append(f"Benefício social dos sócios/administradores: {bs['n_verificados']} verificado(s), nenhum "
                     "recebe benefício de subsistência (indício de laranja afastado para os verificados).")
    if p.get("tem_dados"):
        try:
            from compliance_agent.analysis.benford import benford
            _vals = [ln.get("valor") or 0 for a in p["anos"] for ln in p["por_ano"][a].get("linhas", [])
                     if (ln.get("valor") or 0) > 0]
            _bf = benford(_vals)
            _d1 = _bf.get("primeiro_digito") or {}
            if _bf.get("suficiente") and "NÃO CONFORM" in (_d1.get("faixa_nigrini", "") or "").upper():
                L.append(f"Lei de Benford (1º dígito, n={_d1.get('n')}): NÃO conformidade (MAD {_d1.get('mad')}) — "
                         "indício estatístico de fracionamento/valores fabricados a verificar nos documentos.")
        except Exception:  # noqa: BLE001
            pass
    try:
        rf = _red_flags(ctx)
        if rf:
            L.append("Red flags automáticos disparados: " + "; ".join(t for t, _, _ in rf[:6]) + ".")
    except Exception:  # noqa: BLE001
        pass
    return "\n".join("- " + x for x in L)


_SYS_RACIOCINIO = (
    "Você é auditor sênior de controle externo (padrão TCE-RJ/TCU). A partir EXCLUSIVAMENTE dos fatos "
    "listados (NÃO invente dados, números, nomes ou fontes; não use conhecimento externo), escreva uma "
    "ANÁLISE RACIOCINADA que CONECTE os achados entre si: o que chama atenção, COMO os fatos se "
    "relacionam, quais hipóteses de risco merecem apuração e POR QUÊ, e o que verificar a seguir. Use "
    "linguagem condicional (indício, sugere, merece apuração) — NUNCA afirme fraude/irregularidade nem "
    "culpa; vigora a presunção de regularidade. Responda em MARKDOWN com bullets curtos iniciados por "
    "'- ' (NUNCA JSON, NUNCA cercas de código). Máximo ~320 palavras. Se os fatos forem escassos, diga "
    "objetivamente o que falta apurar."
)


def _normaliza_raciocinio(txt: str) -> str:
    """Limpa a saída do LLM: tira cercas de código e converte JSON/dict (mesmo com aspas simples) em bullets."""
    import ast
    import json as _json
    t = (txt or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", t).strip()

    def _bullets(obj) -> str:
        frases: list[str] = []

        def _walk(o):
            if isinstance(o, str):
                if o.strip():
                    frases.append(o.strip())
            elif isinstance(o, list):
                for x in o:
                    _walk(x)
            elif isinstance(o, dict):
                for x in o.values():
                    _walk(x)
        _walk(obj)
        return "\n".join(f"- {f}" for f in frases)

    if t[:1] in "[{":  # veio estruturado (array ou objeto) — achatar em bullets
        for parser in (_json.loads, ast.literal_eval):
            try:
                b = _bullets(parser(t))
                if b:
                    return b
            except Exception:  # noqa: BLE001
                continue
    return t


def parecer_raciocinado(ctx: dict) -> str:
    """Síntese raciocinada (gemini→cerebras, bounded) sobre os FATOS coletados. '' se LLM indisponível.

    Roda no caminho ASSÍNCRONO (via to_thread no montar) — não bloqueia o event loop; degrada honesto
    (sem regressão: o parecer-template segue como base)."""
    try:
        fatos = _fatos_para_raciocinio(ctx)
        if not fatos.strip():
            return ""
        from compliance_agent.direcionamento_cerebro import gerar_sync
        txt = _normaliza_raciocinio(gerar_sync("FATOS:\n" + fatos, _SYS_RACIOCINIO, timeout=45.0))
        return txt if len(txt) > 80 else ""
    except Exception:  # noqa: BLE001
        return ""


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
    # crescimento — HONESTO: usa pico/base entre exercícios (o 1º e o último da série
    # costumam ser parciais; comparar base→último parcial gera manchete distorcida).
    cresc_txt = ""
    anos_pos = [a for a in p["anos"] if (p["por_ano"][a]["total"] or 0) > 0]
    if len(anos_pos) >= 2:
        a_base = anos_pos[0]
        t_base = p["por_ano"][a_base]["total"]
        a_pico = max(anos_pos, key=lambda a: p["por_ano"][a]["total"])
        t_pico = p["por_ano"][a_pico]["total"]
        mult = _crescimento(p)
        cresc_txt = (f"Os pagamentos saltaram de R$ {moeda(t_base)} ({a_base}) ao pico de R$ {moeda(t_pico)} "
                     f"({a_pico}) — fator pico/base de {mult:.1f}× entre exercícios "
                     "(o primeiro e o último ano da série podem ser parciais; usa-se o pico para evitar distorção). ")
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


def troca_controle_societaria(emp: dict, pagamentos: dict,
                              min_total: float = 1_000_000.0, min_share: float = 15.0) -> dict | None:
    """Detecta ingresso no QSA POSTERIOR a receita pública relevante (controle trocado depois de a
    empresa já ter recebido vulto do Estado). Helper puro reusado pelo /relatorio (RF-04) e pelo Lex.
    Retorna None se não há sinal; senão {recente, quem, total_antes, n_antes, share}."""
    if not emp or not (pagamentos or {}).get("tem_dados"):
        return None
    entradas = [(s.get("data_entrada") or "") for s in (emp.get("socios") or [])]
    entradas = [d for d in entradas if len(d) == 10 and d.count("-") == 2]
    if not entradas:
        return None
    recente = max(entradas)
    total_antes = n_antes = 0
    for a in pagamentos["anos"]:
        for ln in pagamentos["por_ano"][a]["linhas"]:
            d = ln.get("data") or ""
            if len(d) == 10 and d < recente:
                total_antes += ln.get("valor") or 0
                n_antes += 1
    tg = pagamentos.get("total_geral") or 0
    share = (total_antes / tg * 100) if tg else 0
    if total_antes < min_total or share < min_share:
        return None
    nomes = [s.get("nome", "") for s in (emp.get("socios") or [])
             if (s.get("data_entrada") or "") == recente]
    quem = ", ".join(n for n in nomes if n)[:90] or "sócio(s)"
    return {"recente": recente, "quem": quem, "total_antes": total_antes,
            "n_antes": n_antes, "share": share}


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
    # red flag de co-localização (fornecedores na mesma sede) — vindo do cruzamento
    coend = (ctx.get("cruzamento") or {}).get("coendereco") or []
    if coend:
        n_pagos = sum(1 for c in coend if c.get("total_pago", 0) > 0)
        end = (ctx.get("cruzamento") or {}).get("endereco", {}).get("endereco", "")
        out.append((
            "RF-03 — Fornecedores na mesma sede",
            f"{len(coend)} outro(s) fornecedor(es) com sede IDÊNTICA à do alvo ({end}); {n_pagos} também "
            "recebem OBs do Estado. Empresas distintas no mesmo imóvel disputando/recebendo recursos públicos é "
            "indício clássico de fachada/laranja ou direcionamento — verificar QSA, sócios de fato e licitações comuns.",
            "Art. 337-F CP (frustração do caráter competitivo); art. 11 Lei 8.429/92; ACFE — shell company red flags.",
        ))

    # Cadastral (perfil enriquecido) — base das RF-04/05
    emp = (ctx.get("enriq", {}).get("dados") or {}).get("empresa") if ctx.get("enriq", {}).get("ok") else None

    # RF-04 — Alteração de controle societário POSTERIOR a receita pública relevante (helper reusado pelo Lex).
    tc = troca_controle_societaria(emp, p)
    if tc:
        out.append((
            "RF-04 — Controle societário alterado após receita pública relevante",
            f"Ingresso no quadro societário em **{tc['recente']}** ({tc['quem']}), **posterior** a "
            f"R$ {moeda(tc['total_antes'])} já pagos pelo Estado ({tc['n_antes']} OBs, {tc['share']:.0f}% do "
            "total do período). Mudança de controle/administração em fornecedor com receita pública pré-existente "
            "é indício a verificar: histórico de controle, eventual sucessão ou interposição de pessoas, e se a "
            "alteração coincide com escalada de contratos.",
            "Art. 14 Lei 14.133/2021 (idoneidade); art. 11 Lei 8.429/92; ACFE — change-of-control / nominee.",
        ))

    # RF-05 — Possível divergência entre atividade-fim (CNAE) e objeto contratado.
    # Conservador: só dispara quando NÃO há sobreposição de termos significativos (≥4 letras,
    # fora do boilerplate de licitação) entre o CNAE principal e o objeto REAL dos contratos.
    # IMPORTANTE: o campo `contratos.objeto` do SIAFE guarda só "Aditivos: N" (não é o objeto);
    # o objeto verdadeiro vem do TCE-RJ (Dados Abertos) em `tcerj_itens`.
    if emp:
        objs_reais = [(i.get("objeto") or "").strip() for i in (ctx.get("tcerj_itens") or [])]
        objs_reais = [o for o in objs_reais if len(o) >= 12]
        cnae = emp.get("cnae_principal") or ""
        tc = _termos_significativos(cnae)
        to_ = _termos_significativos(" ".join(objs_reais))
        if cnae and objs_reais and tc and to_ and not (tc & to_):
            amostra = objs_reais[0][:70]
            out.append((
                "RF-05 — Atividade-fim (CNAE) sem aderência ao objeto contratado",
                f"O CNAE principal registrado (“{cnae}”) não evidencia aderência ao objeto efetivamente "
                f"contratado (ex.: “{amostra}…”). Atividade econômica de registro incompatível com o objeto "
                "contratado é indício a verificar (adequação do CNAE, pós-fixação de objeto, ou empresa de "
                "prateleira/fachada habilitada para fim diverso).",
                "Art. 37 CF/88 (impessoalidade); Lei 14.133/2021 arts. 62-63 (qualificação técnica); "
                "ACFE — shell company red flags.",
            ))
    return out


# Boilerplate de licitação que NÃO distingue setor (não conta como aderência de objeto×CNAE).
_BOILERPLATE = {
    "contratacao", "contratação", "prestacao", "prestação", "servico", "serviço", "servicos",
    "serviços", "empresa", "pessoa", "juridica", "jurídica", "especializada", "especializado",
    "atividade", "atividades", "outros", "outras", "demais", "fornecimento", "objeto", "trata",
    "presente", "carater", "caráter", "para", "pela", "pelo", "continuado", "continuada",
    "continuos", "contínuos", "diversos", "geral", "comum", "execucao", "execução",
}


def _termos_significativos(texto: str) -> set:
    """Tokens ≥4 letras, fora do boilerplate de licitação — base da aderência CNAE×objeto."""
    return {t for t in re.findall(r"[a-zà-úãõâêôçáéíóú]{4,}", (texto or "").lower())
            if t not in _BOILERPLATE}


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


async def render_pdf_html(ctx: dict, destino: str) -> str:
    """Onda 7 — relatório de fornecedor CLASSE MUNDIAL (HTML→PDF via Playwright).

    Resolve margem estourada e truncamento (CSS quebra texto) e traz TODAS as seções:
    perfil cadastral · quadro societário · DOAÇÕES ELEITORAIS DOS SÓCIOS (conflito) ·
    listas restritivas/OSINT (CEIS/CNEP+OpenSanctions) · pagamentos por ano · concentração ·
    contratos · proveniência + hash. Indícios, nunca acusação.
    """
    import html as _html

    from compliance_agent.reporting import charts_svg as C
    from compliance_agent.reporting.render_html import render_html, html_to_pdf

    def esc(s):
        return _html.escape(str(s if s not in (None, "") else "—"))

    p = ctx["pagamentos"]
    cnpj = ctx["cnpj"]
    emp = (ctx["enriq"].get("dados") or {}).get("empresa") if ctx["enriq"].get("ok") else None
    secoes = []

    # 1. Perfil cadastral
    if emp:
        _endcz = (ctx.get("cruzamento") or {}).get("endereco") or {}  # fallback município/UF (mesma fonte da Seção 1-B)
        _mun = emp.get("municipio") or _endcz.get("municipio") or "—"
        _uf = emp.get("uf") or _endcz.get("uf") or "—"
        campos = [("Razão social", emp.get("razao_social")), ("Situação", emp.get("situacao")),
                  ("Data de abertura", emp.get("data_abertura")), ("Porte", emp.get("porte")),
                  ("Natureza jurídica", emp.get("natureza_juridica")),
                  ("Capital social", f"R$ {moeda(emp.get('capital_social'))}" if emp.get("capital_social") else None),
                  ("CNAE principal", emp.get("cnae_principal")),
                  ("Município/UF", f"{_mun}/{_uf}"),
                  ("Endereço (sede)", emp.get("endereco") or (ctx.get("cruzamento") or {}).get("endereco", {}).get("endereco"))]
        _rs = _realidade_sede_texto(ctx.get("cnpj", ""))
        if _rs:
            campos.append(("Realidade da sede", _rs))  # a empresa é real? (cruzamento de endereço)
        rows = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in campos)
        secoes.append({"titulo": "1. Perfil cadastral", "html": f"<table>{rows}</table>"})
    else:
        end = (ctx.get("cruzamento") or {}).get("endereco", {}).get("endereco")
        _rs = _realidade_sede_texto(ctx.get("cnpj", ""))
        secoes.append({"titulo": "1. Perfil cadastral",
                       "html": f"<p class='nota'>Perfil cadastral {esc(ctx.get('fonte_enriq'))} — dados financeiros abaixo são REAIS."
                               + (f" Endereço (sede): {esc(end)}." if end else "")
                               + (f" Realidade da sede: {esc(_rs)}." if _rs else "") + "</p>"})

    # 2. Quadro societário (sócios/diretores)
    socios = (emp or {}).get("socios") or []
    if socios:
        rows = "".join(f"<tr><td>{esc(s.get('nome'))}</td><td>{esc(s.get('qualificacao'))}</td>"
                       f"<td>{esc(s.get('data_entrada'))}</td></tr>" for s in socios[:25])
        secoes.append({"titulo": "2. Quadro societário (QSA / diretores)",
                       "html": f"<table><tr><th>Sócio</th><th>Qualificação</th><th>Entrada</th></tr>{rows}</table>"})

    # 2-B. Benefícios sociais dos sócios/administradores (laranja) — paridade com o MD §1-C
    try:
        from compliance_agent.reporting import beneficios_view as bv
        _b = bv.por_fornecedor(cnpj)
    except Exception:  # noqa: BLE001
        _b = {}
    _intro_bs = ("<p class='nota'>Cruza o CPF dos sócios/administradores do QSA com benefícios de subsistência "
                 "(Bolsa Família, BPC, Aux. Emergencial, PETI, Safra, Defeso — Portal da Transparência/CGU). Ser "
                 "dono/gestor de empresa que recebe recursos públicos <b>e</b> receber benefício de subsistência é "
                 "<b>indício de testa-de-ferro (laranja)</b> — art. 337-F CP; art. 11 Lei 8.429/92. CPF mascarado "
                 "(LGPD); resolvido via favorecidos PF + doadores TSE. <b>INDISPONÍVEL ≠ ausência.</b> Indício, nunca acusação.</p>")
    if _b.get("total_qsa"):
        _leitura_bs = esc(bv.leitura(_b, escopo="deste fornecedor").replace("**", ""))
        _resumo_bs = (f"<p>QSA mascarado: <b>{_b['total_qsa']}</b> · varridos: {_b['n_varridos']} · CPF resolvido: "
                      f"{_b['n_resolvidos']} · verificados: {_b['n_verificados']} ({_b['cobertura']}%) · com benefício "
                      f"(indício): <b>{_b['n_com_beneficio']}</b> · INDISPONÍVEL: {_b['n_indisponivel']}</p>")
        _fmap_bs = {"favorecidos_pf": "favorecidos PF", "tse_doadores": "doadores TSE"}
        _itens_bs = _b.get("itens") or []
        _tab_bs = ""
        if _itens_bs:
            _rows_bs = "".join(f"<tr><td>{esc(it.get('nome'))}</td><td>{esc(it.get('papel'))}</td>"
                               f"<td>{esc(', '.join(it.get('tipos') or []) or '—')}</td>"
                               f"<td>{esc(_fmap_bs.get(it.get('fonte', ''), it.get('fonte', '') or '—'))}</td></tr>"
                               for it in _itens_bs[:20])
            _tab_bs = ("<table><tr><th>Sócio/Administrador</th><th>Papel</th><th>Benefício</th>"
                       f"<th>Fonte do CPF</th></tr>{_rows_bs}</table>")
        secoes.append({"titulo": "2-B. Benefícios sociais dos sócios/administradores (indício de laranja)",
                       "html": _intro_bs + f"<p>{_leitura_bs}</p>" + _resumo_bs + _tab_bs})
    else:
        secoes.append({"titulo": "2-B. Benefícios sociais dos sócios/administradores",
                       "html": _intro_bs + "<p class='nota'>Sem sócios/administradores com CPF mascarado no QSA "
                               "(ou QSA público não ingerido) — INDISPONÍVEL.</p>"})

    # 3. DOAÇÕES ELEITORAIS dos sócios/empresa (conflito doador↔contrato) — pedido do dono
    # reusa a rede já calculada em montar() (evita 2ª query ao TSE); fallback recalcula
    rede = ctx.get("conflito_rede")
    if rede is None:
        try:
            from compliance_agent.lex_conflito import conflito
            rede = conflito(cnpj=cnpj, limite=30).get("rede", [])
        except Exception:  # noqa: BLE001
            rede = []
    if rede:
        def _ug_cell(r):
            ugs_l = r.get("ugs") or []
            if not ugs_l:
                return "—"
            top = "; ".join(f"{esc(u.get('nome'))} (R$ {moeda(u.get('total'))})" for u in ugs_l[:3])
            extra = f" (+{len(ugs_l) - 3} UG)" if len(ugs_l) > 3 else ""
            return top + extra

        def _sei_cell(r):
            seis_l = r.get("seis") or []
            if not seis_l:
                return "—"
            return ", ".join(esc(s) for s in seis_l[:8]) + (f" (+{len(seis_l) - 8})" if len(seis_l) > 8 else "")

        rows = "".join(f"<tr><td>{esc(r.get('doador'))}</td><td>{esc(r.get('via'))}</td>"
                       f"<td>{esc(r.get('candidato'))}</td><td>{esc(r.get('partido'))}</td>"
                       f"<td>{esc(r.get('ano'))}</td><td>R$ {moeda(r.get('valor_doacao'))}</td>"
                       f"<td>{_ug_cell(r)}</td><td class='nota'>{_sei_cell(r)}</td></tr>" for r in rede[:20])
        secoes.append({"titulo": "3. Doações eleitorais (sócios/empresa → candidatos) — conflito de interesse",
                       "html": "<p class='nota'>Cruzamento TSE × QSA × contratos: o doador pode ser a empresa OU um sócio dela (coluna Via). "
                               "As colunas <b>Órgão (UG) pagador</b> e <b>Processos SEI</b> mostram por onde a empresa contratada recebeu — "
                               "fechando a cadeia doador→fornecedor→candidato→UG→SEI. Indício a verificar (presunção de legitimidade), nunca acusação.</p>"
                               f"<table><tr><th>Doador</th><th>Via</th><th>Candidato</th><th>Partido</th><th>Ano</th><th>Valor doado</th>"
                               f"<th>Órgão (UG) pagador</th><th>Processos SEI</th></tr>{rows}</table>"})
    else:
        secoes.append({"titulo": "3. Doações eleitorais dos sócios/empresa",
                       "html": "<p class='nota'>Nenhuma doação eleitoral (TSE) localizada para a empresa ou seus sócios na base.</p>"})

    # 4. Listas restritivas / OSINT (CEIS/CNEP + OpenSanctions)
    osint = []
    try:
        from compliance_agent.collectors.ceis import verificar_sancao
        s = await verificar_sancao(cnpj)
        if not s.get("verificado"):
            osint.append(f"<li>CEIS/CNEP/CEPIM (CGU): <b>INDISPONÍVEL</b> "
                         f"<span class='nota'>({esc(s.get('motivo') or 'não verificado')}) — não equivale a “limpo”</span></li>")
        elif s.get("sancionado"):
            sl = s.get("sancoes") or []
            top = "; ".join(f"{esc(x.get('_fonte'))}: {esc(x.get('tipo_sancao') or x.get('fundamentacao'))}"
                            for x in sl[:3])
            osint.append(f"<li>CEIS/CNEP/CEPIM (CGU): <b>SANCIONADA — {esc(len(sl))} registro(s)</b> — {top} "
                         f"<span class='nota'>(verificar vigência na fonte)</span></li>")
        else:
            osint.append("<li>CEIS/CNEP/CEPIM (CGU): nada localizado <span class='nota'>(consulta verificada)</span></li>")
    except Exception:  # noqa: BLE001
        osint.append("<li>CEIS/CNEP: INDISPONÍVEL</li>")
    try:
        from compliance_agent.enrich.opensanctions import checar
        o = checar(cnpj)
        osint.append("<li>OpenSanctions (PEP/sanções intl.): INDISPONÍVEL (sem chave grátis)</li>"
                     if o.get("sancionado") is None else
                     f"<li>OpenSanctions: sanção={esc(o.get('sancionado'))} · PEP={esc(o.get('pep'))}</li>")
    except Exception:  # noqa: BLE001
        pass
    try:
        from compliance_agent.enrich.aleph import buscar as _aleph
        al = _aleph(cnpj)
        if not al.get("matches"):
            osint.append("<li>OCCRP Aleph (follow-the-money intl.): INDISPONÍVEL (sem chave grátis) ou sem registro</li>")
        else:
            tops = "; ".join(f"{esc(m.get('nome'))} ({esc(m.get('schema'))})" for m in al["matches"][:3])
            osint.append(f"<li>OCCRP Aleph: <b>{esc(al.get('total'))} registro(s)</b> — {tops} <span class='nota'>(indício a confirmar na fonte)</span></li>")
    except Exception:  # noqa: BLE001
        pass
    gz = ctx.get("gazetas") or {}
    if gz.get("total"):
        muns = "; ".join(dict.fromkeys(
            f"{esc(i.get('municipio'))}/{esc(i.get('uf'))} ({esc(i.get('data'))})"
            for i in (gz.get("itens") or [])[:4] if i.get("municipio")))
        osint.append(f"<li>Diários Oficiais (Querido Diário): <b>{esc(gz['total'])} menção(ões)</b> "
                     f"em diários municipais — {muns} <span class='nota'>(contexto para cotejar contratos além do Estado)</span></li>")
    elif gz.get("_indisponivel"):
        osint.append(f"<li>Diários Oficiais (Querido Diário): INDISPONÍVEL <span class='nota'>({esc(gz['_indisponivel'])})</span></li>")
    secoes.append({"titulo": "4. Listas restritivas e OSINT", "html": f"<ul>{''.join(osint)}</ul>"})

    # 4-C. Mídia adversa (fontes abertas, KEYLESS via GDELT) — DD §9; ideia do dono: usar a internet p/ DD
    try:
        from compliance_agent.enrich.midia_adversa import varrer as _midia
        ma = _midia(ctx.get("nome") or "", cnpj)
        adversos = ma.get("adversos") or []
        if adversos:
            li = "".join(
                f"<li><a href='{esc(a.get('url'))}'>{esc(a.get('titulo'))}</a> "
                f"<span class='nota'>— {esc(a.get('fonte'))} · {esc(a.get('data'))} · termos: {esc(', '.join(a.get('termos') or []))}</span></li>"
                for a in adversos[:10])
            ma_html = (f"<p class='nota'>Varredura de cobertura jornalística (GDELT, fontes abertas, sem chave). "
                       f"{ma.get('n_adversos')} de {ma.get('n_total')} matérias com termos de risco. "
                       "Indício a confirmar na fonte — cobertura não é prova e pode haver homônimos.</p>"
                       f"<ul>{li}</ul>")
        else:
            nota = (ma.get("_nota", "") or "").rstrip(". ")
            ma_html = ("<p class='nota'>Nenhuma matéria com termos de risco localizada em fontes abertas (GDELT)"
                       + (f" — {esc(nota)}" if "INDISPONÍVEL" in nota else " na janela analisada") + ".</p>")
        secoes.append({"titulo": "4-C. Mídia adversa (fontes abertas — OSINT)", "html": ma_html})
    except Exception:  # noqa: BLE001
        pass

    # 4-D. Pistas de investigação hospedada (Max Intel, OSINT-Brazuca, RedeCNPJ…) — deep-links MANUAIS
    try:
        from compliance_agent.providers import lookup as _plookup
        lk = _plookup("links", nome=(ctx.get("nome") or None), cnpj=cnpj)
        links = (lk.dados or {}).get("links") if getattr(lk, "ok", False) else None
        if links:
            li = "".join(f"<li><a href='{esc(x.get('url'))}'>{esc(x.get('fonte'))}</a> "
                         f"<span class='nota'>— {esc(x.get('categoria'))}</span></li>" for x in links)
            secoes.append({"titulo": "4-D. Pistas de investigação (OSINT hospedado — uso manual)",
                           "html": "<p class='nota'>Agregadores e fontes hospedadas grátis (você pesquisa; o JFN só "
                                   "monta o link já preenchido com o alvo). Aprofundamento de DD — não são dados coletados.</p>"
                                   f"<ul>{li}</ul>"})
    except Exception:  # noqa: BLE001
        pass

    # 5. Pagamentos — TABELA CRUZADA Órgão (UG) × Ano (pedido do dono: por ano, dividido por órgão)
    if p["tem_dados"]:
        # agrega valor por (órgão, ano) a partir das linhas de OB
        matriz: dict = {}
        tot_ano: dict = {}
        for a in p["anos"]:
            # por_orgao já é a agregação COMPLETA por órgão naquele exercício
            for org, v in (p["por_ano"][a].get("por_orgao") or {}).items():
                matriz.setdefault(org or "—", {})[a] = v
                tot_ano[a] = tot_ano.get(a, 0.0) + (v or 0)
        orgs_ord = sorted(matriz, key=lambda o: -sum(matriz[o].values()))
        thead = "<tr><th>Órgão (UG)</th>" + "".join(f"<th>{a}</th>" for a in p["anos"]) + "<th>Total</th></tr>"
        body = ""
        for org in orgs_ord:
            tot_org = sum(matriz[org].values())
            cells = "".join(f"<td>{('R$ ' + moeda(matriz[org].get(a, 0))) if matriz[org].get(a) else '—'}</td>" for a in p["anos"])
            body += f"<tr><td>{esc(org)}</td>{cells}<td><b>R$ {moeda(tot_org)}</b></td></tr>"
        body += ("<tr><th>TOTAL</th>" + "".join(f"<th>R$ {moeda(tot_ano.get(a, 0))}</th>" for a in p["anos"])
                 + f"<th>R$ {moeda(p['total_geral'])}</th></tr>")
        spark = C.sparkline([p["por_ano"][a]["total"] for a in p["anos"]], "Total pago por ano")
        # transparência da consolidação: se a empresa tem matriz+filiais (mesma raiz), mostra a quebra
        estab = p.get("por_estabelecimento") or []
        estab_html = ""
        if len(estab) > 1:
            linhas_e = "".join(
                f"<tr><td>{fmt_cnpj(e['cnpj'])}</td><td>{esc(e['tipo'])}</td><td>{esc(e['nome'])}</td>"
                f"<td>{e['n']}</td><td>R$ {moeda(e['total'])}</td></tr>" for e in estab)
            estab_html = (f"<p class='nota'>Empresa consolidada pela <b>raiz {p.get('raiz')}</b> "
                          f"({len(estab)} estabelecimentos — matriz + filiais são <b>uma só pessoa jurídica</b>, "
                          "CC arts. 44/985/1.142 e STJ REsp 1.286.122; o Estado paga cada estabelecimento pelo CNPJ próprio):</p>"
                          "<table><tr><th>CNPJ</th><th>Tipo</th><th>Razão social (na OB)</th><th>OBs</th><th>Pago</th></tr>"
                          f"{linhas_e}</table>")
        secoes.append({"titulo": "5. Pagamentos (Ordens Bancárias) — por Órgão (UG) × Ano",
                       "html": "<p class='nota'>OB = pagamento (dado definitivo, SIAFE/TFE-RJ). Cada célula = total pago "
                               f"àquele órgão naquele exercício ({p['n_geral']} OBs no total). Detalhe por OB individual no XLSX.</p>"
                               + estab_html
                               + f"<table>{thead}{body}</table>",
                       "chart": spark})

        # 5-B. Pagamentos MÊS A MÊS — Órgão × Mês × Ano-exercício (pedido do dono: granularidade mensal de volta)
        mma = p.get("por_orgao_mes_ano") or []
        if mma:
            MESES = {1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
                     7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez", 0: "S/data"}
            presentes = sorted({m for row in mma for m in row["meses"]}, key=lambda m: (m == 0, m))

            def _mc(v):  # valor compacto p/ caber 12+ colunas no A4
                if not v:
                    return "—"
                if abs(v) >= 1e6:
                    return f"{v / 1e6:.2f} mi"
                if abs(v) >= 1e3:
                    return f"{v / 1e3:.0f} mil"
                return f"{v:.0f}"

            thead2 = ("<tr><th>Órgão (UG)</th><th>Exerc.</th>"
                      + "".join(f"<th>{MESES[m]}</th>" for m in presentes) + "<th>Total</th></tr>")
            body2 = ""
            for row in mma:
                cells = "".join(f"<td>{_mc(row['meses'].get(m, 0))}</td>" for m in presentes)
                body2 += (f"<tr><td>{esc(row['orgao'])}</td><td>{row['ano']}</td>{cells}"
                          f"<td><b>R$ {moeda(row['total'])}</b></td></tr>")
            secoes.append({"titulo": "5-B. Pagamentos mês a mês (Órgão × Mês × Ano-exercício)",
                           "html": "<p class='nota'>Granularidade mensal das OBs por órgão e exercício (complementa a tabela "
                                   "cruzada acima). Células em forma compacta (mi = milhões, mil = milhares); o Total fica em "
                                   "precisão cheia e o detalhe por OB individual vai no XLSX. Útil para flagrar pagamentos "
                                   "concentrados em meses atípicos — fim de exercício / véspera eleitoral (red flag ACFE).</p>"
                                   f"<table>{thead2}{body2}</table>"})

        # 5-C. DETALHAMENTO POR OB — cada pagamento com VALOR EXATO + nº da OB (pedido do dono 2026-06-09):
        # nos meses com 2-3 OBs, a 5-B agrega num só número compacto; aqui cada OB aparece em sua linha,
        # com o valor exato e o código da OB. Recente → antigo; lista completa também no XLSX.
        linhas_ob = []
        for _ano, _b in (p.get("por_ano") or {}).items():
            for _ln in _b.get("linhas", []):
                _d = _ln.get("data") or "—"
                _ok = isinstance(_d, str) and len(_d) >= 7 and _d[4:5] == "-"
                _mes = int(_d[5:7]) if _ok else 0
                linhas_ob.append((int(_ano or 0), _mes, _ln, (f"{_d[5:7]}/{_d[0:4]}" if _ok else "s/data")))
        if linhas_ob:
            _LIM = 400
            linhas_ob.sort(key=lambda t: (t[0], t[1], float(t[2].get("valor") or 0)), reverse=True)
            _total_ob = len(linhas_ob)
            _rows = "".join(
                f"<tr><td>{esc(comp)}</td><td>{esc(ln.get('numero_ob') or '—')}</td>"
                f"<td>{esc(ln.get('orgao') or '—')}</td><td>R$ {moeda(ln.get('valor'))}</td></tr>"
                for _a, _m, ln, comp in linhas_ob[:_LIM])
            _nota_cap = (f" Mostrando as {_LIM} OBs mais recentes de {_total_ob}; a lista completa (todas as OBs) "
                         "está na planilha XLSX." if _total_ob > _LIM else "")
            secoes.append({"titulo": "5-C. Detalhamento por OB — valor exato + nº da OB (por mês)",
                           "html": "<p class='nota'>Cada Ordem Bancária com o <b>valor exato</b> e o <b>número da OB</b>, "
                                   "do mês mais recente para o mais antigo. Quando um mês tem dois ou mais pagamentos, "
                                   f"cada um aparece em sua própria linha (a seção 5-B agrega por mês).{_nota_cap}</p>"
                                   "<table><tr><th>Competência</th><th>OB nº</th><th>Órgão (UG)</th>"
                                   f"<th>Valor (R$)</th></tr>{_rows}</table>"})

        # 6. Concentração por órgão (HHI) + barras
        tot = p["total_geral"] or 1
        orgs = list(p["por_orgao_geral"].items())
        bars = C.barras([o for o, _ in orgs[:8]], [v / tot for _, v in orgs[:8]], "Concentração por órgão")
        rows = "".join(f"<tr><td>{esc(o)}</td><td>R$ {moeda(v)}</td><td>{v / tot * 100:.1f}%</td></tr>" for o, v in orgs)
        flag = ("<p class='nota'>🔴 Red flag (ACFE): concentração ≥60% num único órgão sem justificativa pede verificação (Art. 37 CF/88).</p>"
                if p["hhi"].get("top_share", 0) >= 60 else "")
        secoes.append({"titulo": f"6. Concentração por órgão — HHI {p['hhi'].get('indice')} ({p['hhi'].get('nivel')}; maior = {p['hhi'].get('top_share')}%)",
                       "html": f"{flag}<table><tr><th>Órgão (UG)</th><th>Valor pago</th><th>%</th></tr>{rows}</table>",
                       "chart": bars})

    # 7. Contratos — base local (compliance.db) OU TCE-RJ Dados Abertos (fonte oficial, independe do SEI)
    c = ctx["contratos"]
    tcerj_itens = ctx.get("tcerj_itens") or []
    tcerj_contr = [i for i in tcerj_itens if i.get("_tipo") == "contrato"]
    contratado = float(ctx.get("contratado_tcerj") or 0)
    pago = float(p.get("total_geral") or 0)
    if c["n"]:
        rows = "".join(f"<tr><td>{esc(ln['numero'])}</td><td>{esc(ln['objeto'])}</td><td>{esc(ln['orgao'])}</td>"
                       f"<td>R$ {moeda(ln['valor'])}</td><td>{esc(ln['status'])}</td></tr>" for ln in c["linhas"])
        secoes.append({"titulo": f"7. Carteira de contratos ({c['n']} — R$ {moeda(c['total'])})",
                       "html": f"<table><tr><th>Nº</th><th>Objeto</th><th>Órgão</th><th>Valor</th><th>Situação</th></tr>{rows}</table>"})
    elif tcerj_contr:
        tcerj_contr.sort(key=lambda i: (i.get("valor_contrato") or 0), reverse=True)
        rows = "".join(f"<tr><td>{esc(i.get('numero') or i.get('processo'))}</td>"
                       f"<td>{esc((i.get('objeto') or '—')[:70])}</td><td>{esc(i.get('orgao') or i.get('unidade') or '—')}</td>"
                       f"<td>R$ {moeda(i.get('valor_contrato'))}</td></tr>" for i in tcerj_contr[:15])
        gap = (f" <b>Pago (OB) R$ {moeda(pago)} = {pago/contratado:.1f}× o contratado</b> — possíveis aditivos/contratos "
               "não listados, a verificar." if contratado and pago > contratado * 1.2 else "")
        secoes.append({"titulo": f"7. Carteira de contratos — TCE-RJ ({len(tcerj_contr)} — R$ {moeda(contratado)})",
                       "html": "<p class='nota'>Fonte: Dados Abertos do TCE-RJ (controle externo; independe do SEI/WAF). "
                               f"Contratado registrado: R$ {moeda(contratado)}.{gap}</p>"
                               f"<table><tr><th>Nº/Processo</th><th>Objeto</th><th>Órgão</th><th>Valor contrato</th></tr>{rows}</table>"})
    else:
        secoes.append({"titulo": "7. Carteira de contratos",
                       "html": "<p class='nota'>Nenhum contrato formal localizado na base local nem no TCE-RJ Dados Abertos "
                               "para este CNPJ (os pagamentos podem decorrer de atas de registro de preços/adesões — verificar).</p>"})

    # 8. Matriz de risco P×I (TCU) + 9. Análise estatística (Benford)
    if p["tem_dados"]:
        _prob = max(1, min(round((ctx.get("score", 0) or 0) / 11) + 1, 9))
        _imp = max(1, min(round((p["hhi"].get("top_share", 0) or 0) / 100 * 9) + 1, 9))
        secoes.append({"titulo": "8. Matriz de risco P×I (metodologia TCU)",
                       "html": "<p class='nota'>Probabilidade × Impacto (1–9). ✕ marca a posição do achado.</p>",
                       "chart": C.heatmap_pxi(_prob, _imp)})
        try:
            from compliance_agent.analysis.benford import benford
            vals = [ln.get("valor") or 0 for a in p["anos"] for ln in p["por_ano"][a].get("linhas", []) if (ln.get("valor") or 0) > 0]
            bf = benford(vals)
            d1 = bf["primeiro_digito"]
            secoes.append({"titulo": "9. Análise estatística (Lei de Benford)",
                           "html": f"<p class='nota'>1º dígito dos valores de OB (n={d1['n']}). MAD de Nigrini = <b>{d1['mad']}</b> "
                                   f"→ <b>{d1['faixa_nigrini']}</b>. {'Conforme = sem sinal de fracionamento/fabricação.' if 'CONFORM' in d1['faixa_nigrini'].upper() or 'conformidade' in d1['faixa_nigrini'] else 'NÃO conformidade pede verificação (fracionamento/valores fabricados).'} "
                                   f"{'(amostra pequena — pouco confiável)' if not bf['suficiente'] else ''}</p>"})
        except Exception:  # noqa: BLE001
            pass

    # 10. Co-endereço / sócios em comum (sinal de cartel/laranja) — sempre presente (sem buraco de numeração)
    coend = (ctx.get("cruzamento") or {}).get("coendereco") or []
    if coend:
        rows = "".join(f"<tr><td>{esc(x.get('razao') or x.get('cnpj'))}</td><td>{esc(x.get('cnpj'))}</td></tr>" for x in coend[:15])
        secoes.append({"titulo": "10. Empresas no MESMO endereço (sinal de cartel/laranja)",
                       "html": "<p class='nota'>Outras empresas registradas no mesmo endereço da sede — indício de "
                               "fachada/cartel a verificar (não é prova).</p>"
                               f"<table><tr><th>Empresa</th><th>CNPJ</th></tr>{rows}</table>"})
    else:
        secoes.append({"titulo": "10. Empresas no mesmo endereço (cartel/laranja)",
                       "html": "<p class='nota'>Nenhuma outra empresa no mesmo endereço da sede localizada na base "
                               "(não exclui co-endereço fora da base; verificar no RedeCNPJ — seção 4-D).</p>"})

    # 11. Red flags consolidados (com fundamento) — agora alimentados pela CALIBRAGEM (sinais reais)
    cal = ctx.get("calibragem") or {}
    pago = float(p.get("total_geral") or 0)
    contratado = float(ctx.get("contratado_tcerj") or 0)
    flags = []
    if p.get("hhi", {}).get("top_share", 0) >= 60:
        flags.append("🔴 Concentração ≥60% num único órgão (isonomia/impessoalidade — Art. 37 CF/88; ACFE).")
    if contratado and pago > contratado * 1.5:
        flags.append(f"🔴 Pago (R$ {moeda(pago)}) ≫ contratado registrado no TCE-RJ (R$ {moeda(contratado)}) — "
                     f"{pago/contratado:.1f}×: aditivos sucessivos (>25%/50% — arts. 125-126 Lei 14.133) ou contratos não publicados, a verificar.")
    elif contratado and pago > contratado * 1.2:
        flags.append(f"🟡 Pago acima do contratado registrado ({pago/contratado:.1f}×) — verificar aditivos/atas de adesão.")
    if rede:
        flags.append("🟡 Doador eleitoral (empresa/sócio) que é fornecedor — conflito de interesse a verificar (TSE×contratos).")
    if _crescimento(p) >= 4:
        flags.append(f"🟡 Crescimento de faturamento atípico (pico/base = {_crescimento(p):.1f}×) — verificar capacidade operacional vs. salto de receita pública.")
    if coend:
        flags.append("🟡 Empresa(s) no mesmo endereço — possível fachada/cartel (Art. 90 Lei 8.666/Art. 337-F CP).")
    # RF-04/05 (controle societário · CNAE×objeto): fonte ÚNICA em _red_flags(ctx) p/ MD e PDF concordarem.
    for _tit, _desc, _f in _red_flags(ctx):
        if _tit.startswith(("RF-04", "RF-05")):
            _resumo = _desc.split(". ")[0].replace("**", "")
            flags.append("🟡 " + esc(_tit.split("—", 1)[-1].strip()) + ": " + esc(_resumo) + ".")
    if not flags:
        flags.append("🟢 Sem red flags estruturais automáticos nesta triagem (não exclui exame manual).")
    nota_cal = (f"<p class='nota'>Risco JFN recalibrado: <b>{esc(ctx.get('risco'))}</b> (score {ctx.get('score')}/100 = "
                f"máx[externo {cal.get('score_externo',0)}, interno {cal.get('score_interno',0)}]). "
                "Indícios a verificar, nunca acusação (presunção de legitimidade).</p>") if cal else ""
    secoes.append({"titulo": "11. Red flags de compliance (fundamento legal)",
                   "html": nota_cal + "<ul>" + "".join(f"<li>{esc(f)}</li>" for f in flags) + "</ul>"})
    # 11-B. ANÁLISE RACIOCINADA — síntese de IA que CONECTA os achados (cruzamento), sobre os FATOS coletados.
    raciocinio = ctx.get("raciocinio")
    if raciocinio:
        corpo = "".join(f"<li>{esc(b[2:].strip())}</li>" for b in raciocinio.splitlines() if b.strip().startswith("- "))
        corpo_html = f"<ul>{corpo}</ul>" if corpo else f"<p>{esc(raciocinio)}</p>"
        secoes.append({"titulo": "11-B. Análise raciocinada — cruzamento dos achados",
                       "html": corpo_html + "<p class='nota'>Síntese gerada por IA <b>a partir dos fatos coletados "
                               "neste relatório</b> (não inventa dados); indícios para apuração, jamais conclusão de "
                               "irregularidade. O parecer estruturado e os red flags acima permanecem como base.</p>"})
    # recomendações dirigidas pelos achados reais (coerentes com o risco recalibrado)
    if contratado and pago > contratado * 1.5:
        imediato = (f"<b>Imediato:</b> requisitar os termos aditivos e as atas/adesões que expliquem o pago "
                    f"(R$ {moeda(pago)}) ser {pago/contratado:.1f}× o contratado registrado (R$ {moeda(contratado)}) — "
                    "checar limites de 25%/50% (arts. 125-126 Lei 14.133).")
    elif p.get("hhi", {}).get("top_share", 0) >= 40:
        imediato = "<b>Imediato:</b> verificar a motivação técnica da concentração e a pesquisa de preços dos maiores contratos."
    elif (ctx.get("risco") or "").upper() in ("ALTO", "MÉDIO"):
        imediato = "<b>Imediato:</b> abrir diligência sobre os indícios da seção 11 (priorizar os 🔴/🟡 de maior valor)."
    else:
        imediato = "<b>Imediato:</b> manter monitoramento de rotina."
    rec = [imediato,
           "<b>Curto prazo:</b> cruzar doações eleitorais dos sócios com as datas de contratação (conflito de interesse)." if rede else "<b>Curto prazo:</b> confirmar QSA e capacidade operacional (anti-fachada).",
           "<b>Estrutural:</b> consolidar no Radar 24/7 (alerta em novo edital/OB do alvo) e gerar minuta de diligência (TCE-RJ/ALERJ) se confirmado."]
    secoes.append({"titulo": "12. Recomendações (priorizadas)",
                   "html": "<ul>" + "".join(f"<li>{r}</li>" for r in rec) + "</ul>"})
    secoes.append({"titulo": "13. Referências normativas",
                   "html": "<p class='nota'>CF/88 art. 37 e 70-71 · Lei 14.133/2021 · Lei 8.666/93 (contratos vigentes) · "
                           "Lei 4.320/64 (OB = pagamento) · jurisprudência TCU/TCE-RJ (direcionamento, sobrepreço, fracionamento) · "
                           "metodologia P×I (TCU) e red flags (ACFE Report to the Nations).</p>"})

    faixa = (ctx.get("risco") or "BAIXO").upper()
    top = (["concentração ≥60%"] if p.get("hhi", {}).get("top_share", 0) >= 60 else []) + (["doação↔contrato"] if rede else [])
    ctx_html = {
        "_dados": {"cnpj": cnpj, "total": p.get("total_geral"), "score": ctx.get("score")},
        "titulo": f"Relatório de Inteligência — {ctx['nome']}",
        "subtitulo": f"CNPJ {ctx['cnpj_fmt']} · Due Diligence de Integridade · Exposição Financeira · Risco & Compliance",
        "classificacao": "CONFIDENCIAL — USO INTERNO (controle externo)",
        "score": ctx.get("score", 0), "faixa": faixa, "top_flags": top, "secoes": secoes,
        "metodologia": "Due diligence Nível II + red flags TCU/TCE-RJ + conflito TSE",
        "proveniencia": [
            {"dado": "Pagamentos (OB)", "estado": "REAL", "fonte": "SIAFE/TFE", "data": ctx["data"]},
            {"dado": "Cadastro/QSA", "estado": "REAL" if emp else "INDISPONÍVEL", "fonte": "BrasilAPI", "data": ctx["data"]},
            {"dado": "Doações eleitorais", "estado": "REAL", "fonte": "TSE", "data": ctx["data"]},
        ],
    }
    return await html_to_pdf(render_html(ctx_html), destino)


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
            _maiores = sorted(b["linhas"], key=lambda ln: -(ln.get("valor") or 0))[:12]
            _nota = f"{b['n']} OBs — Total pago: R$ {moeda(b['total'])}" + (
                f"  ·  {len(_maiores)} maiores abaixo; lista completa na planilha XLSX" if b["n"] > len(_maiores) else "")
            pdf.cell(0, 6, _t(_nota), ln=True)
            pdf.ln(1)
            _tab_header(pdf, [("#", 10), ("Nº OB", 28), ("Data", 24), ("Órgão (UG)", 90), ("Valor (R$)", 36)])
            pdf.set_font(pdf._fam, "", 7)
            for i, ln in enumerate(_maiores, 1):
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
    raciocinio = ctx.get("raciocinio")
    if raciocinio:
        pdf.set_font(pdf._fam, "B", 11); pdf.cell(0, 7, _t("Análise raciocinada — cruzamento dos achados"), ln=True)
        pdf.set_font(pdf._fam, "", 10)
        _render_parecer_pdf(pdf, _t, raciocinio)
        pdf.ln(2)
    _render_parecer_pdf(pdf, _t, parecer_fornecedor(ctx))

    pdf.ln(3); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(120, 120, 120)
    _mc(pdf, 4, _t("Gerado automaticamente pelo JFN Intelligence Engine. Não substitui análise jurídica especializada."))

    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(destino)
    return destino


def _emit_md_table(pdf, _t, block: list):
    """Renderiza um bloco de tabela markdown como TABELA bordada que CABE na largura da página
    (larguras proporcionais ao conteúdo; trunca cada célula p/ não estourar a margem)."""
    import re as _re
    rows = []
    for ln in block:
        if _re.match(r"^\|[\s:\-|]+\|?$", ln):  # linha separadora |---|
            continue
        rows.append([c.strip() for c in ln.strip().strip("|").split("|")])
    if not rows:
        return
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    epw = pdf.epw
    maxlen = [max((len(_re.sub(r"\*\*", "", rows[i][c])) for i in range(len(rows))), default=1) for c in range(ncol)]
    tot = sum(maxlen) or 1
    widths = [max(11.0, epw * ml / tot) for ml in maxlen]
    f = epw / sum(widths)
    widths = [w * f for w in widths]

    def fit(txt, w):
        txt = _t(_re.sub(r"\*\*(.+?)\*\*", r"\1", txt))
        if pdf.get_string_width(" " + txt + " ") <= w:
            return txt
        while txt and pdf.get_string_width(" " + txt + "… ") > w:
            txt = txt[:-1]
        return txt + "…"

    pdf.set_font(pdf._fam, "B", 7.2); pdf.set_fill_color(60, 70, 90); pdf.set_text_color(255, 255, 255)
    pdf.set_x(pdf.l_margin)
    for c in range(ncol):
        pdf.cell(widths[c], 6, " " + fit(rows[0][c], widths[c]), border=1, fill=True)
    pdf.ln(); pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 7.2)
    zebra = False
    for r in rows[1:]:
        pdf.set_fill_color(244, 246, 250) if zebra else pdf.set_fill_color(255, 255, 255)
        zebra = not zebra
        if pdf.get_y() > pdf.h - pdf.b_margin - 6:
            pdf.add_page()
        pdf.set_x(pdf.l_margin)
        for c in range(ncol):
            cell = r[c]
            num = bool(_re.search(r"\d", cell)) and bool(_re.match(r"^[\sR$\d.,%+\-/]+$", cell))
            pdf.cell(widths[c], 5.0, " " + fit(cell, widths[c]), border=1, align=("R" if num else "L"), fill=True)
        pdf.ln()
    pdf.ln(1.5)


def _render_parecer_pdf(pdf, _t, md_text: str):
    """Renderiza o parecer (markdown leve: ###, **negrito**, '- ', '> ', e TABELAS) no PDF, sem estourar a margem."""
    import re as _re
    linhas = md_text.split("\n")
    i, n = 0, len(linhas)
    while i < n:
        raw = linhas[i].rstrip()
        # bloco de tabela markdown
        if raw.startswith("|") and raw.endswith("|"):
            bloco = []
            while i < n and linhas[i].rstrip().startswith("|"):
                bloco.append(linhas[i].rstrip()); i += 1
            _emit_md_table(pdf, _t, bloco)
            continue
        i += 1
        linha = raw
        if not linha:
            pdf.ln(1.5); continue
        if linha.startswith("### "):
            pdf.ln(1); pdf.set_font(pdf._fam, "B", 11); pdf.set_text_color(30, 45, 70)
            _mc(pdf, 6, _t(linha[4:])); pdf.set_text_color(0, 0, 0); continue
        if linha.startswith("## "):  # cabeçalho de seção (antes saía com '##' literal no PDF)
            pdf.ln(1.5); pdf.set_font(pdf._fam, "B", 12); pdf.set_text_color(20, 35, 60)
            _mc(pdf, 6.5, _t(linha[3:])); pdf.set_text_color(0, 0, 0); continue
        if linha.startswith("# "):
            pdf.ln(2); pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
            _mc(pdf, 7, _t(linha[2:])); pdf.set_text_color(0, 0, 0); continue
        bullet = linha.startswith("- ")
        quote = linha.startswith("> ")
        txt = linha[2:] if (bullet or quote) else linha
        txt = _re.sub(r"\*\*(.+?)\*\*", r"\1", txt)  # remove negrito md
        if quote:
            pdf.set_font(pdf._fam, "I", 8.5); pdf.set_text_color(90, 90, 90)
            _mc(pdf, 4.6, _t(txt)); pdf.set_text_color(0, 0, 0)
        elif bullet:
            pdf.set_font(pdf._fam, "", 9); _mc(pdf, 4.8, _t("•  " + txt))
        else:
            pdf.set_font(pdf._fam, "", 9); _mc(pdf, 4.8, _t(txt))


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
