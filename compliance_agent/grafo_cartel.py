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
        out = []
        for ug, ugn, nf, total, topv, topn, topc, in rows:
            if eh_nao_fornecedor(topn):
                continue
            out.append({
                "ug": ug, "ug_nome": ugn, "n_fornecedores": nf,
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
