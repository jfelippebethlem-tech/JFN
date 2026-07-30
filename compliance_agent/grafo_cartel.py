# -*- coding: utf-8 -*-
"""
Onda 3 — Grafo fornecedor↔órgão: indícios de CAPTURA e CARTEL/RODÍZIO a partir das Ordens Bancárias.

Modela o pagamento público como um grafo bipartido **fornecedor — órgão (UG)**, com peso = R$ pago, e extrai
indícios de controle externo (ACFE/OCDE; CADE Lei 12.529; art. 37 CF/88):

  • captura_orgaos()        — UGs cujo pagamento se concentra em pouquíssimos fornecedores (HHI/top-share alto)
  • dependencia_fornecedores() — fornecedores que vivem de um único órgão (dependência → risco de captura)
  • vizinhanca_cartel(cnpj) — ego-rede de um fornecedor: os órgãos que atende e os OUTROS fornecedores que
                              atuam nos MESMOS órgãos (co-ocorrência = possível rodízio/cartel/bid rigging)

PRINCÍPIO (cláusula de honestidade do JFN): tudo aqui é **indício interno a verificar**, jamais acusação.
Concentração tem explicações legítimas (competência institucional, mercado restrito). Cabe diligência, não juízo.

CLI:
    python -m compliance_agent.grafo_cartel --captura 20
    python -m compliance_agent.grafo_cartel --dependencia 20
    python -m compliance_agent.grafo_cartel --vizinhanca 19088605000104
"""
from __future__ import annotations

import argparse
import json
import re

from compliance_agent.duckdb_util import conectar
from compliance_agent.database.models import _resolver_db


def _hhi(shares: list[float]) -> float:
    """HHI (0–10000) a partir de frações de mercado (0–1)."""
    return round(sum((s * 100) ** 2 for s in shares), 1)


def captura_orgaos(min_fornecedores: int = 5, min_total: float = 1_000_000,
                   limite: int = 30) -> list[dict]:
    """UGs com pagamento concentrado: top-fornecedor com fatia alta apesar de haver vários fornecedores.
    Filtra UGs pequenas (poucos fornecedores/valor baixo) onde concentração é trivial."""
    con = conectar()
    try:
        rows = con.execute("""
            WITH forn AS (
                SELECT ug_codigo, ANY_VALUE(ug_nome) ug_nome, favorecido_cpf,
                       ANY_VALUE(favorecido_nome) nome, SUM(valor) tot
                FROM db.ordens_bancarias WHERE valor > 0 AND favorecido_cpf IS NOT NULL
                GROUP BY ug_codigo, favorecido_cpf
            ), ag AS (
                SELECT ug_codigo, ANY_VALUE(ug_nome) ug_nome, COUNT(*) n_forn, SUM(tot) total,
                       MAX(tot) top_valor,
                       arg_max(nome, tot) top_nome, arg_max(favorecido_cpf, tot) top_cnpj
                FROM forn GROUP BY ug_codigo
            )
            SELECT ug_codigo, ug_nome, n_forn, total, top_valor, top_nome, top_cnpj
            FROM ag WHERE n_forn >= ? AND total >= ?
            ORDER BY (top_valor/total) DESC, total DESC LIMIT ?
        """, [min_fornecedores, min_total, limite * 3 + 10]).fetchall()
        # exclui UGs cujo "top fornecedor" é entidade intra-gov/tributo (Min. Fazenda, Estado, INSS…):
        # 99% indo a um repasse obrigatório NÃO é captura/cartel — é falso-positivo estrutural.
        from compliance_agent.entidades_gov import eh_nao_fornecedor
        from compliance_agent import ugs as _ugs
        out = []
        for ug, ugn, nf, total, topv, topn, topc, in rows:
            if eh_nao_fornecedor(topn):
                continue
            out.append({
                "ug": ug, "ug_nome": _ugs.nome_canonico(str(ug), fallback="") or ugn, "n_fornecedores": nf,
                "total": float(total), "top_share": round(topv / total * 100, 1),
                "top_fornecedor": topn, "top_cnpj": topc,
            })
            if len(out) >= limite:
                break
        return out
    finally:
        con.close()


def dependencia_fornecedores(min_total: float = 1_000_000, limite: int = 30) -> list[dict]:
    """Fornecedores cujo faturamento público vem quase todo de UM órgão (dependência → risco de captura)."""
    con = conectar()
    try:
        rows = con.execute("""
            WITH fu AS (
                SELECT favorecido_cpf, ANY_VALUE(favorecido_nome) nome, ug_codigo, SUM(valor) tot
                FROM db.ordens_bancarias WHERE valor > 0 AND favorecido_cpf IS NOT NULL
                GROUP BY favorecido_cpf, ug_codigo
            ), ag AS (
                SELECT favorecido_cpf, ANY_VALUE(nome) nome, COUNT(*) n_ug, SUM(tot) total,
                       MAX(tot) top_valor, arg_max(ug_codigo, tot) top_ug
                FROM fu GROUP BY favorecido_cpf
            )
            SELECT favorecido_cpf, nome, n_ug, total, top_valor, top_ug
            FROM ag WHERE total >= ?
            ORDER BY (top_valor/total) DESC, total DESC LIMIT ?
        """, [min_total, limite * 3 + 10]).fetchall()
        # exclui não-fornecedores (intra-gov/tributo) — não são "dependentes" de captura
        from compliance_agent.entidades_gov import eh_nao_fornecedor
        out = [{
            "cnpj": c, "nome": n, "n_orgaos": nu, "total": float(t),
            "dependencia_top": round(tv / t * 100, 1), "top_ug": tu,
        } for c, n, nu, t, tv, tu in rows if not eh_nao_fornecedor(n)]
        return out[:limite]
    finally:
        con.close()


def _norm_nome(s: str | None) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s)).strip()


def socios_compartilhados(cnpjs: list[str], max_consultas: int = 20) -> dict:
    """Sócios EM COMUM entre fornecedores que se apresentam como CONCORRENTES = indício de concorrência
    FICTÍCIA / cartel (Art. 90 Lei 8.666 · 337-F CP · Art. 36 Lei 12.529-CADE). Aprofundamento 'c/ QSA' da
    Onda 3: pega o QSA de cada CNPJ (registry provider) e cruza por sócio.

    CAVEAT honesto: o CNPJ público MASCARA o CPF do sócio (***127777**) → o casamento é por NOME (o
    parcial do CPF corrobora). Nome pode ser ambíguo → INDÍCIO a conferir, NUNCA acusação."""
    from compliance_agent.providers import lookup
    socio2cnpjs: dict[str, set] = {}
    doc2cnpjs: dict[str, set] = {}
    consultados, falhas = [], []
    for c in list(dict.fromkeys(re.sub(r"\D", "", x or "") for x in cnpjs if x))[:max_consultas]:
        r = lookup("registry", cnpj=c)
        if not r.ok or not r.dados:
            falhas.append(c); continue
        consultados.append(c)
        for s in (r.dados.get("socios") or []):
            nome = _norm_nome(s.get("nome"))
            if len(nome) > 5:
                socio2cnpjs.setdefault(nome, set()).add(c)
            doc = re.sub(r"\D", "", s.get("doc") or "")
            if len(doc) >= 6:  # parcial mascarado corrobora
                doc2cnpjs.setdefault(doc, set()).add(c)
    compart = [{"socio": nome, "cnpjs": sorted(cs), "n": len(cs)}
               for nome, cs in socio2cnpjs.items() if len(cs) >= 2]
    compart.sort(key=lambda x: -x["n"])
    return {"n_consultados": len(consultados), "n_falhas": len(falhas),
            "socios_compartilhados": compart, "n_socios_comuns": len(compart),
            "red_flag": bool(compart),
            "nota": "Sócio em comum entre concorrentes = indício de concorrência fictícia (Art. 90); conferir. "
                    "CPF público mascarado → casamento por nome."}


# ------------------------------------------------------------- concentração COLAPSADA por grupo econômico
_NOTA_GRUPO = (
    "Concentração colapsada por GRUPO econômico (CNPJs ligados por sócio em comum, dedup por raiz). "
    "Muitos CNPJs que parecem concorrentes mas são UM grupo = diversidade fictícia / possível fracionamento "
    "ou concorrência simulada (Art. 90 Lei 8.666 · 337-F CP · Art. 36 Lei 12.529-CADE). Indício a corroborar "
    "com editais/licitantes (SEI/PNCP); QSA mascarado/indisponível ≠ afastado. Nunca acusação.")


def _uniao_por_socio(cnpjs: list[str], socios: dict[str, set]) -> dict[str, str]:
    """Union-find: une CNPJs (por RAIZ-8) que partilham ≥1 sócio (`socio_nome_norm`). Matriz/filial (mesma
    raiz) já caem juntos. Retorna {cnpj14: grupo_id}, grupo_id = menor raiz do componente (determinístico)."""
    pai: dict[str, str] = {}

    def find(x: str) -> str:
        pai.setdefault(x, x)
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            pai[max(ra, rb)] = min(ra, rb)  # liga sempre para a menor raiz → id estável

    raiz = {c: c[:8] for c in cnpjs}
    for c in cnpjs:
        find(raiz[c])
    socio2raiz: dict[str, set] = {}
    for c in cnpjs:
        for s in socios.get(c, ()):  # socio_nome_norm já normalizado
            if s:
                socio2raiz.setdefault(s, set()).add(raiz[c])
    for rs in socio2raiz.values():
        ordenadas = sorted(rs)
        for r in ordenadas[1:]:
            union(ordenadas[0], r)
    return {c: find(raiz[c]) for c in cnpjs}


def _metrica_grupos(totais: dict[str, float], nomes: dict[str, str], gid: dict[str, str]) -> dict:
    """Agrega R$ por grupo e mede a concentração (HHI por grupo vs por CNPJ; grupo multi-raiz dominante)."""
    grupos: dict[str, dict] = {}
    for c, t in totais.items():
        g = gid.get(c, c[:8])
        e = grupos.setdefault(g, {"grupo": g, "cnpjs": [], "raizes": set(), "total": 0.0,
                                  "top_nome": "", "top_val": -1.0})
        e["cnpjs"].append(c)
        e["raizes"].add(c[:8])
        e["total"] += t
        if t > e["top_val"]:
            e["top_val"], e["top_nome"] = t, nomes.get(c, "")
    grand = sum(totais.values()) or 1.0
    lst = [{"grupo": e["grupo"], "n_cnpjs": len(e["cnpjs"]), "n_raizes": len(e["raizes"]),
            "total": round(e["total"], 2), "share": round(e["total"] / grand * 100, 2),
            "top_nome": e["top_nome"], "cnpjs": sorted(e["cnpjs"])} for e in grupos.values()]
    lst.sort(key=lambda x: -x["total"])
    hhi_grupo = _hhi([x["total"] / grand for x in lst])
    hhi_cnpj = _hhi([t / grand for t in totais.values()])
    multi = [x for x in lst if x["n_raizes"] >= 2]
    maior_multi = max(multi, key=lambda x: x["total"], default=None)
    return {"n_cnpjs": len(totais), "n_grupos": len(lst), "n_grupos_multi": len(multi),
            "hhi_cnpj": hhi_cnpj, "hhi_grupo": hhi_grupo, "delta_hhi": round(hhi_grupo - hhi_cnpj, 1),
            "top_grupo_share": lst[0]["share"] if lst else 0.0,
            "maior_grupo_multi": maior_multi, "grupos": lst}


def concentracao_por_grupo(ug: str, *, top_n: int = 200, min_share_grupo: float = 15.0) -> dict:
    """Concentração de uma UG COLAPSADA por grupo econômico — DELEGA a `osint/grupo_economico`.

    ESTA FUNÇÃO ERA UMA SEGUNDA IMPLEMENTAÇÃO, e era a pior das duas. Medido na SECID (UG 660100),
    o caso emblemático da casa:

                              |  osint/grupo_economico  |  esta função, antes
      HHI por CNPJ            |         0,1062          |       0,1020
      HHI por GRUPO           |         0,4064          |       0,3254
      share do maior grupo    |         62,1%           |       53,27%

    Subestimava a concentração em 8,8 pontos de share — e é o delta que constitui o achado. Três
    causas, todas no código: (a) unia por `socio_nome_norm`, nome puro, que a régua da casa avalia em
    força 0,10; (b) media sobre `ordens_bancarias`, o espelho TFE, contra a regra absoluta nº 2 do
    projeto ("OB/pagamento → SEMPRE SIAFE direto"); (c) não tinha guarda de fan-out, de modo que um
    sócio serial ou um homônimo podia fundir meio acervo num grupo só.

    O CONTRATO DE RETORNO É PRESERVADO byte a byte — inclusive a escala 0-10000 do HHI —, porque o
    detector J1 (peso 0,9) e a §1-H do relatório de órgão o consomem. `tests/
    test_grupo_economico_paridade.py` trava cada campo. O que se acrescenta é `cobertura_qsa`, que a
    antiga não tinha: fornecedor sem QSA conta como grupo de si mesmo, então **o delta é PISO**.

    `top_n` deixou de ter efeito (a medição nova não amostra os maiores — usa a UG inteira) e
    permanece na assinatura só para não quebrar chamador existente.
    """
    import sqlite3 as _sq

    from compliance_agent import ugs as _ugs
    from compliance_agent.osint.grupo_economico import concentracao_da_ug, montar_grupos

    con = _sq.connect(f"file:{_resolver_db()}?mode=ro", uri=True)
    try:
        base = concentracao_da_ug(con, str(ug), grupos=montar_grupos(con))
    finally:
        con.close()

    nome_ug = _ugs.nome_canonico(str(ug), fallback="") or ""
    if base.get("estado") != "medido":
        return {"ug": str(ug), "ug_nome": nome_ug, "indicio": False,
                "n_cnpjs": 0, "n_grupos": 0, "n_grupos_multi": 0,
                "hhi_cnpj": 0.0, "hhi_grupo": 0.0, "delta_hhi": 0.0, "top_grupo_share": 0.0,
                "maior_grupo_multi": None, "grupos": [],
                "cobertura_qsa": base.get("cobertura_qsa"),
                "nota": base.get("motivo") or _NOTA_GRUPO}

    # escala: a nova mede HHI em 0-1; esta função sempre devolveu 0-10000, e os renders assumem isso
    def _e(v) -> float:
        return round(float(v or 0.0) * 10000, 1)

    grupos = []
    for g in base.get("maiores_grupos") or []:
        cnpjs = g.get("cnpjs") or []
        grupos.append({
            "grupo": g.get("grupo"),
            "n_cnpjs": g.get("n_cnpj") or len(cnpjs),
            "n_raizes": len({c[:8] for c in cnpjs}) or 1,
            "total": g.get("valor"),
            "share": round(float(g.get("fracao") or 0.0) * 100, 2),
            "top_nome": (g.get("unido_por") or [""])[0],
            "cnpjs": sorted(cnpjs),
            "unido_por": g.get("unido_por") or [],
        })
    multi = [x for x in grupos if (x["n_cnpjs"] or 0) >= 2]
    maior_multi = max(multi, key=lambda x: x["total"] or 0, default=None)
    top_share = grupos[0]["share"] if grupos else 0.0
    return {
        "ug": str(ug), "ug_nome": nome_ug,
        "indicio": bool(maior_multi and (maior_multi["share"] or 0) >= min_share_grupo),
        "n_cnpjs": base.get("n_cnpj", 0), "n_grupos": base.get("n_grupo", 0),
        "n_grupos_multi": len(multi),
        "hhi_cnpj": _e(base.get("hhi_por_cnpj")), "hhi_grupo": _e(base.get("hhi_por_grupo")),
        "delta_hhi": _e(base.get("delta_hhi")),
        "top_grupo_share": top_share,
        "maior_grupo_multi": maior_multi, "grupos": grupos,
        "cobertura_qsa": base.get("cobertura_qsa"),
        "total_pago": base.get("total_pago"),
        "nota": _NOTA_GRUPO + " " + (base.get("ressalva") or ""),
    }


def cartel_com_qsa(cnpj: str, limite: int = 15, max_ubiquidade: int = 40) -> dict:
    """Onda 3 completa: ego-rede de cartel (vizinhanca_cartel) + cruzamento de QSA entre o alvo e os
    vizinhos co-ocorrentes (socios_compartilhados). Indício de rodízio COM concorrência fictícia."""
    viz = vizinhanca_cartel(cnpj, limite=limite, max_ubiquidade=max_ubiquidade)
    cnpjs = [cnpj] + [v["cnpj"] for v in viz.get("vizinhos", [])]
    qsa = socios_compartilhados(cnpjs)
    return {"cnpj": re.sub(r"\D", "", cnpj or ""), "vizinhanca": viz, "qsa_cruzado": qsa}


def vizinhanca_cartel(cnpj: str, limite: int = 15, max_ubiquidade: int = 40) -> dict:
    """Ego-rede de um fornecedor: os órgãos que atende e os OUTROS fornecedores nos MESMOS órgãos.

    EXCLUI fornecedores **ubíquos** (ativos em mais de `max_ubiquidade` órgãos — utilities/tributos/Light/
    Águas/telefonia, que aparecem em quase todo órgão e geram co-ocorrência espúria). O que sobra são players
    que partilham um conjunto ESTREITO de órgãos com o alvo — aí sim co-ocorrência é indício de rodízio/cartel."""
    cnpj = re.sub(r"\D", "", cnpj or "")
    con = conectar()
    try:
        ugs = con.execute("""
            SELECT ug_codigo, ANY_VALUE(ug_nome) ug_nome, SUM(valor) tot
            FROM db.ordens_bancarias WHERE favorecido_cpf = ? AND valor > 0
            GROUP BY ug_codigo ORDER BY tot DESC
        """, [cnpj]).fetchall()
        if not ugs:
            return {"cnpj": cnpj, "orgaos": [], "vizinhos": [], "n_orgaos": 0}
        ug_codes = [u[0] for u in ugs]
        ph = ",".join("?" * len(ug_codes))
        # co-ocorrência nos mesmos órgãos, EXCLUINDO fornecedores ubíquos (footprint total grande)
        viz = con.execute(f"""
            WITH foot AS (   -- footprint total de cada fornecedor (em quantos órgãos atua no total)
                SELECT favorecido_cpf, COUNT(DISTINCT ug_codigo) n_ug_total
                FROM db.ordens_bancarias WHERE valor > 0 GROUP BY favorecido_cpf
            )
            SELECT o.favorecido_cpf, ANY_VALUE(o.favorecido_nome) nome,
                   COUNT(DISTINCT o.ug_codigo) ugs_comuns, SUM(o.valor) valor_nesses_orgaos,
                   ANY_VALUE(f.n_ug_total) n_ug_total
            FROM db.ordens_bancarias o JOIN foot f USING (favorecido_cpf)
            WHERE o.ug_codigo IN ({ph}) AND o.favorecido_cpf != ? AND o.valor > 0
                  AND f.n_ug_total <= ?
            GROUP BY o.favorecido_cpf
            ORDER BY ugs_comuns DESC, valor_nesses_orgaos DESC LIMIT ?
        """, ug_codes + [cnpj, max_ubiquidade, limite]).fetchall()
        return {
            "cnpj": cnpj,
            "n_orgaos": len(ugs),
            "orgaos": [{"ug": u, "ug_nome": n, "total": float(t)} for u, n, t in ugs[:limite]],
            "vizinhos": [{"cnpj": c, "nome": n, "orgaos_comuns": k, "valor_nos_orgaos": float(v),
                          "footprint_total": ft}
                         for c, n, k, v, ft in viz],
        }
    finally:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Grafo fornecedor↔órgão — indícios de captura/cartel (Onda 3).")
    ap.add_argument("--captura", type=int, metavar="N", help="top N UGs por concentração")
    ap.add_argument("--dependencia", type=int, metavar="N", help="top N fornecedores dependentes de 1 órgão")
    ap.add_argument("--vizinhanca", type=str, metavar="CNPJ", help="ego-rede de cartel de um CNPJ")
    a = ap.parse_args()
    if a.captura:
        print(json.dumps(captura_orgaos(limite=a.captura), ensure_ascii=False, indent=2, default=str))
    if a.dependencia:
        print(json.dumps(dependencia_fornecedores(limite=a.dependencia), ensure_ascii=False, indent=2, default=str))
    if a.vizinhanca:
        print(json.dumps(vizinhanca_cartel(a.vizinhanca), ensure_ascii=False, indent=2, default=str))
