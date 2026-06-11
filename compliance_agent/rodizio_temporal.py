# -*- coding: utf-8 -*-
"""
Rodízio temporal de cartel — vencedores que se REVEZAM no topo de uma UG ano a ano (bid rotation).

Complementa o `grafo_cartel` (co-ocorrência ESPACIAL fornecedor↔órgão) com o eixo que faltava: o TEMPO.
Padrão clássico de bid rigging (OCDE *Guidelines for Fighting Bid Rigging*, 2009; ACFE; CADE Lei 12.529):
um conjunto ESTREITO de fornecedores domina o gasto de uma UG e ALTERNA quem fica em 1º a cada exercício —
cada um "ganha a sua vez". Isso difere de CONCENTRAÇÃO/dependência (um só fornecedor sempre no topo), que já
é coberta por `grafo_cartel.captura_orgaos`/`dependencia_fornecedores`.

O indício de rodízio exige, ao mesmo tempo:
  • conjunto estreito de CAMPEÕES (≥ `min_campeoes` CNPJs distintos ficaram em 1º em algum ano);
  • ALTERNÂNCIA real (o 1º troca de mãos — `alternancia` = trocas / (anos-1) ≥ `min_alternancia`);
  • DOMINÂNCIA (os campeões capturam ≥ `min_share_ring` do gasto da UG no período);
  • histórico suficiente (≥ `min_anos` exercícios).

HONESTIDADE (cláusula JFN): a OB registra o VENCEDOR (pagamento), não a lista de licitantes. Logo isto é
**indício interno a verificar** — rodízio de vencedores recorrentes a corroborar com a lista de propostas
(SEI/PNCP). Há explicações legítimas (mercado restrito, especialização). Cabe diligência, nunca acusação.

CLI:
    python -m compliance_agent.rodizio_temporal --ug 036100
    python -m compliance_agent.rodizio_temporal --varredura 30
"""
from __future__ import annotations

import argparse
import json
import re

_NOTA = ("OB = vencedor/pagamento, não a lista de licitantes → indício de rodízio de vencedores a "
         "corroborar com as propostas (SEI/PNCP). Mercado restrito/especialização explica parte; "
         "indício a verificar, nunca acusação.")


def _detectar_rodizio(por_ano: dict[int, list[dict]], *, min_anos: int = 3, min_campeoes: int = 3,
                      min_alternancia: float = 0.5, min_share_ring: float = 0.6,
                      eh_excluido=None) -> dict:
    """Núcleo PURO (sem DB). `por_ano`: {exercicio: [{cnpj, nome, valor}, ...]} já agregado por CNPJ/ano.

    `eh_excluido(nome)->bool` remove entidades que não são fornecedores de verdade (repasse intra-gov/
    tributo) antes de eleger o campeão do ano. Retorna o veredito + os campeões e a sequência anual."""
    anos = sorted(por_ano)
    total_por_cnpj: dict[str, float] = {}
    nome_por_cnpj: dict[str, str] = {}
    grand = 0.0
    campeao_ano: dict[int, str] = {}
    for ano in anos:
        rows = [r for r in por_ano[ano] if (r.get("valor") or 0) > 0
                and not (eh_excluido and eh_excluido(r.get("nome") or ""))]
        if not rows:
            continue
        for r in rows:
            c = r["cnpj"]
            total_por_cnpj[c] = total_por_cnpj.get(c, 0.0) + float(r["valor"])
            nome_por_cnpj.setdefault(c, (r.get("nome") or "").strip())
            grand += float(r["valor"])
        top = max(rows, key=lambda r: r["valor"])
        campeao_ano[ano] = top["cnpj"]

    anos_validos = sorted(campeao_ano)
    seq = [campeao_ano[a] for a in anos_validos]
    n_anos = len(seq)

    campeoes: dict[str, dict] = {}
    for a in anos_validos:
        c = campeao_ano[a]
        campeoes.setdefault(c, {"cnpj": c, "nome": nome_por_cnpj.get(c, ""), "anos": []})["anos"].append(a)
    for c, e in campeoes.items():
        e["n_vitorias"] = len(e["anos"])
        e["total"] = round(total_por_cnpj.get(c, 0.0), 2)
    n_campeoes = len(campeoes)

    trocas = sum(1 for i in range(1, n_anos) if seq[i] != seq[i - 1])
    alternancia = round(trocas / (n_anos - 1), 3) if n_anos > 1 else 0.0
    ring_total = sum(total_por_cnpj.get(c, 0.0) for c in campeoes)
    share_ring = round(ring_total / grand, 3) if grand > 0 else 0.0
    # score contínuo (0–100) p/ ranqueamento entre UGs: dominância + alternância + tamanho do anel
    score = round(100 * (0.4 * share_ring + 0.4 * alternancia + 0.2 * min(n_campeoes / 5.0, 1.0)), 1)
    indicio = bool(n_anos >= min_anos and n_campeoes >= min_campeoes
                   and alternancia >= min_alternancia and share_ring >= min_share_ring)

    return {
        "indicio": indicio, "score": score,
        "n_anos": n_anos, "n_campeoes": n_campeoes,
        "alternancia": alternancia, "share_ring": share_ring,
        "anos": anos_validos,
        "campeoes": sorted(campeoes.values(), key=lambda e: (-e["n_vitorias"], -e["total"])),
        "sequencia": [{"ano": a, "cnpj": campeao_ano[a], "nome": nome_por_cnpj.get(campeao_ano[a], "")}
                      for a in anos_validos],
        "nota": _NOTA,
    }


# --------------------------------------------------------------------------- camada de dados (DuckDB)
def _por_ano_da_ug(con, ug: str) -> dict[int, list[dict]]:
    """Agrega gasto por (exercício, CNPJ) numa UG. Só PJ (CNPJ 14 díg); ignora PF/folha."""
    rows = con.execute("""
        SELECT exercicio, favorecido_cpf, ANY_VALUE(favorecido_nome) nome, SUM(valor) tot
        FROM db.ordens_bancarias
        WHERE ug_codigo = ? AND valor > 0 AND favorecido_cpf IS NOT NULL
              AND length(regexp_replace(favorecido_cpf, '[^0-9]', '', 'g')) = 14
        GROUP BY exercicio, favorecido_cpf
    """, [str(ug)]).fetchall()
    por_ano: dict[int, list[dict]] = {}
    for ex, cnpj, nome, tot in rows:
        if ex is None:
            continue
        por_ano.setdefault(int(ex), []).append(
            {"cnpj": re.sub(r"\D", "", cnpj or ""), "nome": nome or "", "valor": float(tot or 0.0)})
    return por_ano


def rodizio_orgao(ug: str, *, min_anos: int = 3, min_campeoes: int = 3,
                  min_alternancia: float = 0.5, min_share_ring: float = 0.6) -> dict:
    """Detecta rodízio temporal de vencedores numa UG (sobre as Ordens Bancárias)."""
    from compliance_agent.duckdb_util import conectar
    from compliance_agent.entidades_gov import eh_nao_fornecedor
    from compliance_agent import ugs as _ugs
    con = conectar()
    try:
        por_ano = _por_ano_da_ug(con, ug)
    finally:
        con.close()
    res = _detectar_rodizio(por_ano, min_anos=min_anos, min_campeoes=min_campeoes,
                            min_alternancia=min_alternancia, min_share_ring=min_share_ring,
                            eh_excluido=eh_nao_fornecedor)
    res["ug"] = str(ug)
    res["ug_nome"] = _ugs.nome_canonico(str(ug), fallback="") or ""
    return res


def rodizio_varredura(min_total: float = 1_000_000, limite: int = 30, **kw) -> list[dict]:
    """Varre todas as UGs e ranqueia as com indício de rodízio temporal (score desc)."""
    from compliance_agent.duckdb_util import conectar
    from compliance_agent.entidades_gov import eh_nao_fornecedor
    from compliance_agent import ugs as _ugs
    con = conectar()
    try:
        rows = con.execute("""
            SELECT ug_codigo, exercicio, favorecido_cpf, ANY_VALUE(favorecido_nome) nome, SUM(valor) tot
            FROM db.ordens_bancarias
            WHERE valor > 0 AND favorecido_cpf IS NOT NULL
                  AND length(regexp_replace(favorecido_cpf, '[^0-9]', '', 'g')) = 14
            GROUP BY ug_codigo, exercicio, favorecido_cpf
        """).fetchall()
    finally:
        con.close()
    por_ug: dict[str, dict[int, list[dict]]] = {}
    total_ug: dict[str, float] = {}
    for ug, ex, cnpj, nome, tot in rows:
        if ug is None or ex is None:
            continue
        ug = str(ug)
        por_ug.setdefault(ug, {}).setdefault(int(ex), []).append(
            {"cnpj": re.sub(r"\D", "", cnpj or ""), "nome": nome or "", "valor": float(tot or 0.0)})
        total_ug[ug] = total_ug.get(ug, 0.0) + float(tot or 0.0)
    achados = []
    for ug, por_ano in por_ug.items():
        if total_ug.get(ug, 0.0) < min_total:
            continue
        r = _detectar_rodizio(por_ano, eh_excluido=eh_nao_fornecedor, **kw)
        if r["indicio"]:
            r["ug"] = ug
            r["ug_nome"] = _ugs.nome_canonico(ug, fallback="") or ""
            r["total_ug"] = round(total_ug.get(ug, 0.0), 2)
            achados.append(r)
    achados.sort(key=lambda r: -r["score"])
    return achados[:limite]


def _moeda(v: float) -> str:
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ 0,00"


def render_md(r: dict) -> str:
    """Relatório legível de um achado de rodízio (uma UG)."""
    L = [f"# Rodízio temporal — UG {r.get('ug','?')} {r.get('ug_nome','')}".rstrip(), ""]
    if not r.get("indicio"):
        L.append(f"Sem indício de rodízio (campeões={r.get('n_campeoes')}, anos={r.get('n_anos')}, "
                 f"alternância={r.get('alternancia')}, dominância={r.get('share_ring')}).")
        L += ["", f"> {r.get('nota','')}"]
        return "\n".join(L)
    L += [f"**INDÍCIO de rodízio** · score {r['score']} · {r['n_campeoes']} campeões revezando o 1º em "
          f"{r['n_anos']} exercícios (alternância {r['alternancia']}, dominância {r['share_ring']}).", "",
          "| Exercício | Vencedor (1º) | CNPJ |", "|---|---|---|"]
    for s in r["sequencia"]:
        L.append(f"| {s['ano']} | {s['nome'][:40]} | {s['cnpj']} |")
    L += ["", "**Campeões (revezamento):**", "| Fornecedor | CNPJ | Vitórias | Total na UG |", "|---|---|--:|--:|"]
    for c in r["campeoes"]:
        L.append(f"| {c['nome'][:40]} | {c['cnpj']} | {c['n_vitorias']} | {_moeda(c['total'])} |")
    L += ["", f"> {r['nota']}"]
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Rodízio temporal de cartel (bid rotation) sobre as OBs.")
    ap.add_argument("--ug", type=str, metavar="UG", help="detecta rodízio numa UG (ex.: 036100)")
    ap.add_argument("--varredura", type=int, metavar="N", help="top N UGs com indício de rodízio")
    a = ap.parse_args()
    if a.ug:
        print(render_md(rodizio_orgao(a.ug)))
    if a.varredura:
        out = rodizio_varredura(limite=a.varredura)
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
