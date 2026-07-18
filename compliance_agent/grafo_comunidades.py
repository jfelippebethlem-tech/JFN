# -*- coding: utf-8 -*-
"""grafo_comunidades — detecção de COMUNIDADES (Louvain) no grafo família-empresa-órgão.

Nós: pessoa (sócio do QSA Receita), empresa (cnpj_basico — matriz e filiais fundidas) e
órgão (comprador PNCP ou UG pagadora SIAFE). Arestas: sócio→empresa (QSA), empresa→órgão
(vitória PNCP / OB SIAFE, peso ~ log do valor) e empresa↔empresa (co-participação no mesmo
certame). Louvain (networkx, seed fixa = determinístico) revela os CLUSTERS densos de
dinheiro+societário; cada comunidade recebe um SCORE DE RISCO 0-100 por sinais objetivos:

    +30 par de conluio direto dentro da comunidade (conluio_qsa: vencedor×perdedora, QSA comum)
    +20 empresa SANCIONADA (CEIS/CNEP impeditiva) na comunidade
    +20 empresa com fantasma_score ALTO
    +15 sócio que é SERVIDOR público (socios_fornecedor.socio_servidor)
    +15 concentração: ≥60% do valor da comunidade vem de UM único órgão

Determinístico, sem IA. Indício ≠ acusação — a comunidade densa é o MAPA de onde olhar.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_DB = str(_REPO / "data" / "compliance.db")

logger = logging.getLogger(__name__)

RESSALVA = ("Comunidade densa = proximidade societária/comercial, não prova de conluio. "
            "Score é triagem interna (escala 0-100 documentada acima). Indício ≠ acusação; "
            "CPF de sócio permanece mascarado (LGPD).")


def _ro(db_path: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path or _DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _q(con, sql, args=()):
    """Consulta tolerante: tabela ausente (fixture parcial) → lista vazia, nunca crash."""
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError as exc:
        logger.debug("grafo_comunidades: %s", exc)
        return []


def construir_grafo_intel(db_path: str | None = None):
    """Grafo NetworkX não-direcionado e ponderado com os 3 tipos de nó."""
    import networkx as nx
    G = nx.Graph()
    con = _ro(db_path)
    try:
        # nomes de empresa (empresas_min cobre 74k raízes; PNCP cobre fornecedores ativos)
        nome_emp: dict[str, str] = {}
        for r in _q(con, "SELECT cnpj_basico, razao_social FROM empresas_min"):
            nome_emp.setdefault(r["cnpj_basico"], r["razao_social"])
        for r in _q(con, "SELECT DISTINCT substr(fornecedor_cnpj,1,8) b, fornecedor_nome "
                         "FROM pncp_resultado WHERE fornecedor_nome IS NOT NULL"):
            nome_emp.setdefault(r["b"], r["fornecedor_nome"])

        def _emp(basico: str):
            nid = f"emp:{basico}"
            if nid not in G:
                G.add_node(nid, tipo="empresa", label=(nome_emp.get(basico) or basico)[:48],
                           basico=basico, valor=0.0, cnpjs=set())
            return nid

        # sócio → empresa (QSA do dump da Receita; conselheiro fica — aqui é mapa, não veredito)
        for r in _q(con, "SELECT cnpj_basico, nome_socio, nome_norm, doc_socio "
                         "FROM socios_receita WHERE nome_norm<>''"):
            frag = "".join(c for c in (r["doc_socio"] or "") if c.isdigit())
            pid = f"pes:{r['nome_norm']}|{frag}"
            if pid not in G:
                G.add_node(pid, tipo="pessoa", label=(r["nome_socio"] or "")[:48])
            G.add_edge(pid, _emp(r["cnpj_basico"]), tipo="socio", weight=2.0)

        # empresa → órgão comprador (vitórias PNCP; peso cresce com o log do valor)
        for r in _q(con, "SELECT substr(fornecedor_cnpj,1,8) b, fornecedor_cnpj, orgao_cnpj, "
                         "orgao_nome, SUM(valor_homologado) v FROM pncp_resultado "
                         "WHERE (ordem_classificacao=1 OR (ordem_classificacao IS NULL "
                         "AND valor_homologado>0)) AND length(fornecedor_cnpj)=14 "
                         "GROUP BY b, orgao_cnpj"):
            oid = f"org:{r['orgao_cnpj']}"
            if oid not in G:
                G.add_node(oid, tipo="orgao", label=(r["orgao_nome"] or r["orgao_cnpj"])[:48])
            eid = _emp(r["b"])
            v = r["v"] or 0.0
            G.nodes[eid]["valor"] += v
            G.nodes[eid]["cnpjs"].add(r["fornecedor_cnpj"])
            w = 1.0 + math.log1p(v) / 4
            G.add_edge(eid, oid, tipo="vitoria",
                       weight=max(w, G.get_edge_data(eid, oid, {}).get("weight", 0)))

        # empresa → UG pagadora (OB SIAFE = dinheiro que SAIU; verdade do pagamento)
        try:
            ug_nome = json.loads((_REPO / "data" / "ug_index_siafe.json").read_text())["ugs"]
        except (OSError, ValueError, KeyError):
            ug_nome = {}
        for r in _q(con, "SELECT substr(credor,1,8) b, credor, ug_emitente ug, SUM(valor) v "
                         "FROM ob_orcamentaria_siafe WHERE length(credor)=14 AND valor>0 "
                         "GROUP BY b, ug_emitente"):
            oid = f"org:ug{r['ug']}"
            if oid not in G:
                G.add_node(oid, tipo="orgao", label=(ug_nome.get(r["ug"]) or f"UG {r['ug']}")[:48])
            eid = _emp(r["b"])
            v = r["v"] or 0.0
            G.nodes[eid]["valor"] += v
            G.nodes[eid]["cnpjs"].add(r["credor"])
            w = 1.0 + math.log1p(v) / 4
            G.add_edge(eid, oid, tipo="pagamento",
                       weight=max(w, G.get_edge_data(eid, oid, {}).get("weight", 0)))

        # empresa ↔ empresa: co-participação REPETIDA (≥2 certames juntos). Uma co-ocorrência
        # avulsa é ruído de mercado (colaria o setor inteiro num mega-cluster); par que disputa
        # junto repetidamente é o sinal OCDE de rodízio/cobertura.
        cert: dict[str, set] = {}
        for r in _q(con, "SELECT certame, substr(fornecedor_cnpj,1,8) b FROM pncp_resultado "
                         "WHERE length(fornecedor_cnpj)=14"):
            cert.setdefault(r["certame"], set()).add(r["b"])
        juntos: dict[tuple, int] = {}
        for basicos in cert.values():
            bs = sorted(basicos)
            if not (2 <= len(bs) <= 20):        # >20 = pregão gigante, co-ocorrência não diz nada
                continue
            for i, a in enumerate(bs):
                for b in bs[i + 1:]:
                    juntos[(a, b)] = juntos.get((a, b), 0) + 1
        for (a, b), n in juntos.items():
            if n >= 2:
                G.add_edge(_emp(a), _emp(b), tipo="coparticipacao", weight=float(n))
    finally:
        con.close()
    return G


def _sinais_risco(con, comunidade_basicos: set[str], pares_conluio: list) -> tuple[int, list]:
    """Score 0-100 da comunidade pelos 5 sinais objetivos (pesos no docstring do módulo)."""
    sinais, score = [], 0
    par_dentro = [p for p in pares_conluio
                  if p["vencedor"]["cnpj"][:8] in comunidade_basicos
                  and p["perdedora"]["cnpj"][:8] in comunidade_basicos]
    if par_dentro:
        score += 30
        p0 = par_dentro[0]
        sinais.append({"sinal": "conluio_direto", "peso": 30,
                       "detalhe": f"{p0['vencedor']['nome'][:30]} × {p0['perdedora']['nome'][:30]}"
                                  f" ({len(par_dentro)} par(es))"})
    marc = ",".join("?" * len(comunidade_basicos))
    bs = sorted(comunidade_basicos)
    sanc = _q(con, "SELECT DISTINCT substr(cpf_cnpj,1,8) b, nome FROM sancoes_federais "
                   f"WHERE length(cpf_cnpj)=14 AND substr(cpf_cnpj,1,8) IN ({marc})", bs)
    if sanc:
        score += 20
        sinais.append({"sinal": "sancionada", "peso": 20,
                       "detalhe": (sanc[0]["nome"] or sanc[0]["b"])[:40]})
    fant = _q(con, "SELECT razao_social FROM fantasma_score WHERE classificacao='alto' "
                   f"AND substr(cnpj,1,8) IN ({marc})", bs)
    if fant:
        score += 20
        sinais.append({"sinal": "fantasma_alto", "peso": 20,
                       "detalhe": (fant[0]["razao_social"] or "")[:40]})
    serv = _q(con, "SELECT socio_nome FROM socios_fornecedor WHERE socio_servidor=1 "
                   f"AND substr(cnpj,1,8) IN ({marc})", bs)
    if serv:
        score += 15
        sinais.append({"sinal": "socio_servidor", "peso": 15,
                       "detalhe": (serv[0]["socio_nome"] or "")[:40]})
    return score, sinais


def detectar_comunidades(db_path: str | None = None, min_tamanho: int = 4, top: int = 30,
                         seed: int = 42, incluir_grafo_d3: bool = True) -> dict:
    """Louvain na PROJEÇÃO pessoa+empresa → comunidades ranqueadas por risco (0-100) e valor.

    O Louvain roda SEM os nós de órgão: um órgão-hub (SEEDUC compra de 1.300 empresas) grudaria
    fornecedores sem NENHUMA relação num mega-cluster de densidade ~0. O clã real é o tecido
    societário (sócio↔empresa) + disputas em comum; os órgãos entram depois, como contexto de
    cada comunidade (de onde vem o dinheiro) e no sinal de concentração."""
    import networkx as nx
    G = construir_grafo_intel(db_path)
    if G.number_of_nodes() == 0:
        return {"ok": False, "erro": "grafo vazio — coletar PNCP/QSA antes"}
    H = G.subgraph(n for n in G if not n.startswith("org:"))
    comm = nx.community.louvain_communities(H, weight="weight", seed=seed)

    pares = []
    try:
        from compliance_agent.cruzamentos_intel import conluio_qsa, ler_cache_intel
        if db_path is None:      # cache global só vale p/ o DB de produção
            pares = (ler_cache_intel("conluio_qsa") or {}).get("pares") or []
        if not pares:
            pares = conluio_qsa(db_path, incluir_atas=False).get("pares", [])
    except Exception as exc:
        logger.warning("comunidades sem pares de conluio: %s", exc)

    con = _ro(db_path)
    out = []
    try:
        for cid, nodes in enumerate(comm):
            emps = [n for n in nodes if n.startswith("emp:")]
            pess = [n for n in nodes if n.startswith("pes:")]
            if len(nodes) < min_tamanho or not emps or not pess:
                continue        # sem mistura pessoa+empresa não há "clã" a mapear
            basicos = {G.nodes[e]["basico"] for e in emps}
            valor = sum(G.nodes[e]["valor"] for e in emps)
            score, sinais = _sinais_risco(con, basicos, pares)
            # órgãos ANEXADOS (contexto): de onde vem o dinheiro das empresas do clã.
            # Valor da empresa rateado entre seus órgãos (proxy) p/ o teste de concentração.
            por_org: dict[str, float] = {}
            for e in emps:
                viz_orgs = [v for v in G.neighbors(e) if v.startswith("org:")]
                for v in viz_orgs:
                    por_org[v] = por_org.get(v, 0.0) + G.nodes[e]["valor"] / len(viz_orgs)
            if valor > 0 and por_org and max(por_org.values()) / max(valor, 1e-9) >= 0.60:
                score += 15
                dom = max(por_org, key=por_org.get)
                sinais.append({"sinal": "orgao_dominante", "peso": 15,
                               "detalhe": G.nodes[dom]["label"]})
            orgs_top = sorted(por_org, key=por_org.get, reverse=True)[:5]
            sub = H.subgraph(nodes)
            membros = sorted(nodes, key=lambda n: -sub.degree(n))
            out.append({
                "id": cid, "score": min(score, 100),
                "rating": "🔴" if score >= 50 else ("🟡" if score >= 20 else "🟢"),
                "sinais": sinais, "valor_total": valor,
                "n_empresas": len(emps), "n_pessoas": len(pess), "n_orgaos": len(por_org),
                "densidade": round(nx.density(sub), 3),
                "membros": [{"id": n, "tipo": G.nodes[n]["tipo"],
                             "label": G.nodes[n]["label"],
                             "grau": sub.degree(n)} for n in membros[:30]]
                           + [{"id": o, "tipo": "orgao", "label": G.nodes[o]["label"],
                               "grau": 0} for o in orgs_top],
            })
    finally:
        con.close()
    out.sort(key=lambda c: (-c["score"], -c["valor_total"]))
    out = out[:top]

    d3 = None
    if incluir_grafo_d3 and out:
        top_nodes = [m["id"] for c in out[:10] for m in c["membros"]][:600]
        sub = G.subgraph(top_nodes)
        com_de = {m["id"]: c["id"] for c in out[:10] for m in c["membros"]}
        d3 = {"nodes": [{"id": n, "label": sub.nodes[n]["label"], "tipo": sub.nodes[n]["tipo"],
                         "comunidade": com_de.get(n), "valor": sub.nodes[n].get("valor", 0.0)}
                        for n in sub.nodes],
              "links": [{"source": u, "target": v, "tipo": sub.edges[u, v]["tipo"],
                         "weight": round(sub.edges[u, v].get("weight", 1.0), 2)}
                        for u, v in sub.edges]}

    return {"ok": True, "comunidades": out, "n": len(out),
            "grafo": {"nos": G.number_of_nodes(), "arestas": G.number_of_edges(),
                      "comunidades_brutas": len(comm)},
            "d3": d3, "articuladores": articuladores(H, seed=seed),
            "escala": ("Score 0-100: conluio direto +30, sancionada +20, fantasma alto +20, "
                       "sócio-servidor +15, órgão dominante (≥60% do valor) +15. "
                       "🔴 ≥50 · 🟡 20-49 · 🟢 <20."),
            "explicacao": ("Louvain agrupa quem está 'perto' por sociedade, disputas em comum "
                           "e dinheiro dos mesmos órgãos. O cluster denso família-empresa-órgão "
                           "é o desenho clássico do grupo econômico oculto atrás de licitações."),
            "ressalva": RESSALVA}


def articuladores(G, top: int = 25, seed: int = 42) -> list[dict]:
    """Pessoas/empresas-PONTE (betweenness amostrado): quem conecta comunidades — o perfil
    do articulador/laranja profissional que aparece em vários grupos sem ser o dono formal."""
    import networkx as nx
    n = G.number_of_nodes()
    if n < 3:
        return []
    bc = nx.betweenness_centrality(G, k=min(300, n), seed=seed, weight=None)
    rank = sorted(bc.items(), key=lambda x: -x[1])[:top]
    return [{"id": nid, "tipo": G.nodes[nid]["tipo"], "label": G.nodes[nid]["label"],
             "centralidade": round(v, 5), "grau": G.degree(nid)}
            for nid, v in rank if v > 0]


if __name__ == "__main__":
    import sys
    d = detectar_comunidades(top=int(sys.argv[1]) if len(sys.argv) > 1 else 15,
                             incluir_grafo_d3=False)
    if not d.get("ok"):
        print(d)
        sys.exit(1)
    g = d["grafo"]
    print(f"grafo: {g['nos']} nós, {g['arestas']} arestas, {g['comunidades_brutas']} comunidades")
    for c in d["comunidades"]:
        s = "; ".join(f"{x['sinal']}({x['detalhe'][:24]})" for x in c["sinais"]) or "—"
        print(f"{c['rating']} [{c['score']:3}] emp={c['n_empresas']:3} pes={c['n_pessoas']:3} "
              f"org={c['n_orgaos']:2} R${c['valor_total']:>14,.0f} dens={c['densidade']:.2f} | {s}")
    print("\nARTICULADORES (pontes):")
    for a in d["articuladores"][:10]:
        print(f"  {a['tipo']:8} {a['label'][:40]:40} bc={a['centralidade']} grau={a['grau']}")
