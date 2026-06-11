# -*- coding: utf-8 -*-
"""Investigação de Due Diligence PRIORIZADA por órgão (UG) — triagem de fachada/laranja em lote.

Dado um órgão (UG), roda o motor `investigacao_dd.investigar` nos seus maiores fornecedores PJ e os
**ranqueia por grau/score de DD**, destacando os candidatos a fachada/laranja e os **processos (SEI) a
priorizar** no sweep. É o "investigar órgão" pedido p/ TJRJ (030100) e Fundo Especial do TJ (036100).

Network-light por padrão: o lote roda com `usar_beneficios=False` (não dispara PEP/benefício em massa —
isso fica para o /relatorio individual do alvo, via Lex). `usar_rede=True` aproveita a base local
(co-endereço). Bounded por `top_n`. HONESTO: grau 🟢 não é "limpo", é "sem indício nas hipóteses
verificáveis"; INDISPONÍVEL ≠ 0; indício ≠ acusação. CPF de PF mascarado nos produtos (LGPD).
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from compliance_agent.investigacao_dd import investigar

_DB = Path("data") / "compliance.db"
_ORDEM_GRAU = {"🔴": 0, "🟡": 1, "🟢": 2}


def _digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _moeda(v: float) -> str:
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ 0,00"


def top_fornecedores_pj(ug: str, *, top_n: int | None = 15, anos: list[int] | None = None,
                        ordem: str = "desc", db_path: str | Path | None = None) -> list[dict]:
    """Fornecedores PJ (CNPJ de 14 díg) de uma UG, por total pago (OB = pagamento).

    top_n=None → todos (p/ varrer a cauda). ordem='asc' → menores primeiro (cauda fachada-prone)."""
    p = Path(db_path or _DB)
    if not p.exists():
        return []
    direcao = "ASC" if ordem == "asc" else "DESC"
    q = ("SELECT favorecido_cpf, MAX(favorecido_nome), ROUND(SUM(valor),2), COUNT(*), MIN(data_pagamento) "
         "FROM ordens_bancarias WHERE ug_codigo=? AND valor>0")
    params: list = [str(ug)]
    if anos:
        q += " AND exercicio IN (%s)" % ",".join("?" * len(anos))
        params += [str(a) for a in anos]
    q += f" GROUP BY favorecido_cpf ORDER BY SUM(valor) {direcao}"
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        rows = con.execute(q, params).fetchall()
    finally:
        con.close()
    out = []
    for cpf, nome, total, n, primeira in rows:
        c = _digitos(cpf)
        if len(c) != 14:  # só PJ (PF/folha fora da triagem de fachada)
            continue
        out.append({"cnpj": c, "nome": (nome or "—").strip(), "total_pago": float(total or 0.0),
                    "n_obs": int(n or 0), "primeira_data": primeira})
        if top_n is not None and len(out) >= top_n:
            break
    return out


def _processos_do_fornecedor(ug: str, cnpj: str, db_path: str | Path | None = None, limite: int = 20) -> list[str]:
    """Processos (numero_sei | numero_processo) das OBs do fornecedor na UG — alvos do sweep SEI."""
    p = Path(db_path or _DB)
    if not p.exists():
        return []
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT DISTINCT COALESCE(NULLIF(numero_sei,''), numero_processo) FROM ordens_bancarias "
            "WHERE ug_codigo=? AND replace(replace(replace(favorecido_cpf,'.',''),'-',''),'/','')=? "
            "AND COALESCE(NULLIF(numero_sei,''), numero_processo) IS NOT NULL", (str(ug), cnpj)).fetchall()
    finally:
        con.close()
    procs = sorted({(r[0] or "").strip() for r in rows if (r[0] or "").strip()})
    return procs[:limite]


def investigar_orgao(ug: str, *, top_n: int = 15, anos: list[int] | None = None,
                     usar_beneficios: bool = False, incluir_rodizio: bool = True,
                     db_path: str | Path | None = None) -> dict:
    """Triagem de DD nos maiores fornecedores PJ da UG, ranqueada por grau/score.

    Retorna {ug, n_avaliados, ranking:[{cnpj,nome,total_pago,grau,score,n_indicios,n_confirmados,
    codigos,processos_sei}], alvos_prioritarios, processos_prioritarios, rodizio, resumo}.

    `rodizio` = indício de rodízio temporal de vencedores na UG (bid rotation) — só calculado em produção
    (db_path None; o DuckDB ataca o compliance.db real). Degrada honesto (None se falhar).
    """
    forns = top_fornecedores_pj(ug, top_n=top_n, anos=anos, db_path=db_path)
    ranking: list[dict] = []
    for f in forns:
        inv = investigar(f["cnpj"], pagamentos={"total_pago": f["total_pago"], "primeira_data": f["primeira_data"]},
                         usar_rede=True, geocode=False, usar_beneficios=usar_beneficios)
        procs = _processos_do_fornecedor(ug, f["cnpj"], db_path=db_path) if inv["grau"] != "🟢" else []
        ranking.append({**f, "grau": inv["grau"], "score": inv["score"],
                        "n_indicios": inv["n_indicios"], "n_confirmados": inv["n_confirmados"],
                        "codigos": sorted({h["codigo"] for h in inv["hipoteses"]
                                           if h["status"] in ("CONFIRMADO", "INDICIO")}),
                        "processos_sei": procs})
    ranking.sort(key=lambda r: (_ORDEM_GRAU.get(r["grau"], 9), -r["score"], -r["total_pago"]))
    alvos = [r for r in ranking if r["grau"] != "🟢"]
    procs_prior = sorted({p for r in alvos for p in r["processos_sei"]})
    resumo = (f"{len(ranking)} fornecedor(es) PJ avaliado(s) na UG {ug}; "
              f"{len([r for r in ranking if r['grau'] == '🔴'])} 🔴, "
              f"{len([r for r in ranking if r['grau'] == '🟡'])} 🟡. "
              f"{len(procs_prior)} processo(s) a priorizar no sweep SEI. "
              "Grau 🟢 = sem indício nas hipóteses verificáveis (não é atestado de regularidade); "
              "indício merece apuração, não é acusação.")
    rodizio = None
    if incluir_rodizio and db_path is None:
        try:
            from compliance_agent import rodizio_temporal
            rod = rodizio_temporal.rodizio_orgao(str(ug))
            rodizio = rod if rod.get("indicio") else {"indicio": False, "ug": str(ug)}
        except Exception:  # noqa: BLE001 — degrada honesto
            rodizio = None
    return {"ug": str(ug), "n_avaliados": len(ranking), "ranking": ranking,
            "alvos_prioritarios": alvos, "processos_prioritarios": procs_prior,
            "rodizio": rodizio, "resumo": resumo}


def render_md(out: dict) -> str:
    """Tabela de triagem priorizada (markdown) — para inspeção/CLI."""
    L = [f"# Triagem de Due Diligence — UG {out['ug']}", "", out["resumo"], ""]
    rod = out.get("rodizio")
    if rod and rod.get("indicio"):
        camps = ", ".join(f"{c['nome'][:24]} ({c['n_vitorias']}x)" for c in rod.get("campeoes", [])[:4])
        L += [f"**⟳ Rodízio temporal (bid rotation):** score {rod.get('score')}, {rod.get('n_campeoes')} "
              f"campeões revezando o 1º em {rod.get('n_anos')} exercícios (alternância {rod.get('alternancia')}, "
              f"dominância {rod.get('share_ring')}). {camps}. Indício a corroborar (SEI/PNCP).", ""]
    L += ["| # | Grau | Score | Fornecedor | Total pago | Indícios | Processos SEI |",
          "|--:|:--:|--:|---|--:|---|--:|"]
    for i, r in enumerate(out["ranking"], 1):
        cods = ", ".join(c.replace("H-", "") for c in r["codigos"]) or "—"
        L.append(f"| {i} | {r['grau']} | {r['score']} | {r['nome'][:40]} | {_moeda(r['total_pago'])} "
                 f"| {cods} | {len(r['processos_sei'])} |")
    if out["processos_prioritarios"]:
        L += ["", "**Processos a priorizar no sweep SEI:** " + ", ".join(out["processos_prioritarios"][:30])]
    return "\n".join(L)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Triagem de DD priorizada por órgão (UG)")
    ap.add_argument("ug", help="código da UG (ex.: 030100 TJRJ, 036100 Fundo TJ)")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--beneficios", action="store_true", help="ativa PEP/benefício no lote (mais lento)")
    a = ap.parse_args()
    print(render_md(investigar_orgao(a.ug, top_n=a.top, usar_beneficios=a.beneficios)))
